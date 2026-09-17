from __future__ import annotations

import argparse
import inspect
import json
import math
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
    set_seed,
)

ROOT = Path(__file__).resolve().parents[1]

TRAIN_FILE = ROOT / "data" / "processed" / "training" / "stage1_exact" / "train_balanced.jsonl"
VAL_FILE = ROOT / "data" / "processed" / "training" / "stage1_exact" / "validation_balanced.jsonl"
OUTPUT_DIR = ROOT / "models" / "paper-qwen-lora"

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

SEED = 42
MAX_LENGTH = 768
TRAIN_BATCH_SIZE = 1
EVAL_BATCH_SIZE = 1
GRAD_ACCUM = 8

LEARNING_RATE = 5e-5
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.08
NUM_EPOCHS = 4

EVAL_STEPS = 10
SAVE_STEPS = 10
LOGGING_STEPS = 5
SAVE_TOTAL_LIMIT = 3
EARLY_STOPPING_PATIENCE = 3

LORA_R = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.05

TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]

SYSTEM_PROMPT = (
    "You are an academic paper drafting model. "
    "Write only the requested section in a formal academic style. "
    "Do not invent citations or references."
)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_no} JSON 오류: {exc}") from exc

            instruction = str(obj.get("instruction", "")).strip()
            user_input = str(obj.get("input", "")).strip()
            output = str(obj.get("output", "")).strip()

            if not instruction or not output:
                continue

            rows.append({
                "instruction": instruction,
                "input": user_input,
                "output": output,
                "section": obj.get("section", ""),
                "paper_id": obj.get("paper_id", ""),
            })
    return rows


def print_gpu_info():
    print("=" * 70)
    print("환경 확인")
    print("=" * 70)
    print("PyTorch:", torch.__version__)
    print("CUDA 사용 가능:", torch.cuda.is_available())

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU가 인식되지 않습니다.")

    print("CUDA:", torch.version.cuda)
    print("GPU:", torch.cuda.get_device_name(0))
    props = torch.cuda.get_device_properties(0)
    print(f"VRAM: {props.total_memory / (1024 ** 3):.2f} GB")


def find_latest_checkpoint(output_dir: Path) -> str | None:
    if not output_dir.exists():
        return None

    checkpoints = []
    for path in output_dir.glob("checkpoint-*"):
        if not path.is_dir():
            continue
        try:
            step = int(path.name.split("-")[-1])
        except ValueError:
            continue
        checkpoints.append((step, path))

    if not checkpoints:
        return None

    checkpoints.sort(key=lambda x: x[0])
    return str(checkpoints[-1][1])


def make_user_message(row: dict) -> str:
    if row["input"]:
        return f'{row["instruction"]}\n\nResearch topic:\n{row["input"]}'
    return row["instruction"]


def build_tokenizer():
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        use_fast=True,
        trust_remote_code=True,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def tokenize_row(row: dict, tokenizer):
    prompt_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": make_user_message(row)},
    ]

    full_messages = [
        *prompt_messages,
        {"role": "assistant", "content": row["output"]},
    ]

    prompt_text = tokenizer.apply_chat_template(
        prompt_messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    full_text = tokenizer.apply_chat_template(
        full_messages,
        tokenize=False,
        add_generation_prompt=False,
    )

    prompt_tokens = tokenizer(
        prompt_text,
        add_special_tokens=False,
        truncation=True,
        max_length=MAX_LENGTH,
    )

    full_tokens = tokenizer(
        full_text,
        add_special_tokens=False,
        truncation=True,
        max_length=MAX_LENGTH,
    )

    input_ids = full_tokens["input_ids"]
    attention_mask = full_tokens["attention_mask"]
    labels = input_ids.copy()

    prompt_len = min(len(prompt_tokens["input_ids"]), len(labels))
    labels[:prompt_len] = [-100] * prompt_len

    if sum(1 for x in labels if x != -100) < 8:
        labels = [-100] * len(labels)

    return {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "labels": labels,
    }


def build_model():
    # 최신 transformers는 dtype 사용
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.float16,
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )

    model.config.use_cache = False
    model.gradient_checkpointing_enable()

    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
        target_modules=TARGET_MODULES,
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    return model


def make_training_args(smoke_test: bool, train_sample_count: int):
    """
    transformers 버전에 따라 TrainingArguments 인자명이 바뀌는 문제를 피하기 위한
    호환성 래퍼.
    """
    sig = inspect.signature(TrainingArguments.__init__)
    supported = set(sig.parameters.keys())

    max_steps = 10 if smoke_test else -1
    epochs = 1 if smoke_test else NUM_EPOCHS

    kwargs = {
        "output_dir": str(OUTPUT_DIR),
        "num_train_epochs": epochs,
        "max_steps": max_steps,
        "per_device_train_batch_size": TRAIN_BATCH_SIZE,
        "per_device_eval_batch_size": EVAL_BATCH_SIZE,
        "gradient_accumulation_steps": GRAD_ACCUM,
        "learning_rate": LEARNING_RATE,
        "weight_decay": WEIGHT_DECAY,
        "fp16": True,
        "bf16": False,
        "gradient_checkpointing": True,
        "optim": "adamw_torch",
        "eval_steps": EVAL_STEPS,
        "save_steps": SAVE_STEPS,
        "save_total_limit": SAVE_TOTAL_LIMIT,
        "logging_steps": LOGGING_STEPS,
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "report_to": "none",
        "seed": SEED,
        "data_seed": SEED,
        "remove_unused_columns": False,
        "dataloader_num_workers": 0,
        "dataloader_pin_memory": True,
    }

    # warmup_ratio 지원 여부
    if "warmup_ratio" in supported:
        kwargs["warmup_ratio"] = WARMUP_RATIO
    elif "warmup_steps" in supported:
        if smoke_test:
            kwargs["warmup_steps"] = 1
        else:
            effective_batch = TRAIN_BATCH_SIZE * GRAD_ACCUM
            steps_per_epoch = max(1, math.ceil(train_sample_count / effective_batch))
            total_steps = max(1, steps_per_epoch * NUM_EPOCHS)
            kwargs["warmup_steps"] = max(1, round(total_steps * WARMUP_RATIO))

    # evaluation/eval strategy 인자명 호환
    if "eval_strategy" in supported:
        kwargs["eval_strategy"] = "steps"
    elif "evaluation_strategy" in supported:
        kwargs["evaluation_strategy"] = "steps"

    if "save_strategy" in supported:
        kwargs["save_strategy"] = "steps"

    if "logging_strategy" in supported:
        kwargs["logging_strategy"] = "steps"

    # 지원되지 않는 인자는 자동 제거
    filtered = {k: v for k, v in kwargs.items() if k in supported}

    print("\n[TrainingArguments 호환 설정]")
    print("사용 인자:", sorted(filtered.keys()))

    return TrainingArguments(**filtered)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    set_seed(SEED)
    print_gpu_info()

    if not TRAIN_FILE.exists():
        raise FileNotFoundError(f"학습 파일 없음: {TRAIN_FILE}")
    if not VAL_FILE.exists():
        raise FileNotFoundError(f"검증 파일 없음: {VAL_FILE}")

    train_rows = load_jsonl(TRAIN_FILE)
    val_rows = load_jsonl(VAL_FILE)

    print("\n" + "=" * 70)
    print("데이터")
    print("=" * 70)
    print("Train:", len(train_rows))
    print("Validation:", len(val_rows))

    tokenizer = build_tokenizer()

    train_dataset = Dataset.from_list(train_rows)
    val_dataset = Dataset.from_list(val_rows)

    train_dataset = train_dataset.map(
        lambda row: tokenize_row(row, tokenizer),
        remove_columns=train_dataset.column_names,
        desc="Train 토큰화",
    )

    val_dataset = val_dataset.map(
        lambda row: tokenize_row(row, tokenizer),
        remove_columns=val_dataset.column_names,
        desc="Validation 토큰화",
    )

    train_dataset = train_dataset.filter(
        lambda row: any(x != -100 for x in row["labels"])
    )
    val_dataset = val_dataset.filter(
        lambda row: any(x != -100 for x in row["labels"])
    )

    print("\n실제 Train sample:", len(train_dataset))
    print("실제 Validation sample:", len(val_dataset))

    model = build_model()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    training_args = make_training_args(
        smoke_test=args.smoke_test,
        train_sample_count=len(train_dataset),
    )

    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        model=model,
        padding=True,
        label_pad_token_id=-100,
        return_tensors="pt",
    )

    callbacks = []
    if not args.smoke_test:
        callbacks.append(
            EarlyStoppingCallback(
                early_stopping_patience=EARLY_STOPPING_PATIENCE,
                early_stopping_threshold=0.0,
            )
        )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=data_collator,
        callbacks=callbacks,
    )

    resume_checkpoint = None
    if not args.fresh and not args.smoke_test:
        resume_checkpoint = find_latest_checkpoint(OUTPUT_DIR)

    if resume_checkpoint:
        print("\n기존 checkpoint에서 자동 재개:")
        print(resume_checkpoint)
    else:
        print("\n새 학습을 시작합니다.")

    print("\n" + "=" * 70)
    print("SMOKE TEST" if args.smoke_test else "본 학습 시작")
    print("=" * 70)

    train_result = trainer.train(
        resume_from_checkpoint=resume_checkpoint
    )

    final_dir = OUTPUT_DIR / "best_adapter"
    final_dir.mkdir(parents=True, exist_ok=True)

    trainer.save_model(str(final_dir))
    tokenizer.save_pretrained(str(final_dir))

    metrics = dict(train_result.metrics)
    eval_metrics = trainer.evaluate()

    metrics.update({
        f"final_{key}": value
        for key, value in eval_metrics.items()
    })

    if "final_eval_loss" in metrics:
        try:
            metrics["final_perplexity"] = math.exp(metrics["final_eval_loss"])
        except OverflowError:
            metrics["final_perplexity"] = float("inf")

    metrics["best_checkpoint"] = trainer.state.best_model_checkpoint
    metrics["base_model"] = BASE_MODEL
    metrics["max_length"] = MAX_LENGTH
    metrics["lora_r"] = LORA_R
    metrics["lora_alpha"] = LORA_ALPHA
    metrics["lora_dropout"] = LORA_DROPOUT
    metrics["train_samples"] = len(train_dataset)
    metrics["validation_samples"] = len(val_dataset)

    metrics_path = OUTPUT_DIR / (
        "smoke_test_metrics.json"
        if args.smoke_test
        else "training_metrics.json"
    )

    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 70)
    if args.smoke_test:
        print("SMOKE TEST 완료")
        print("다음 명령으로 본 학습:")
        print("python paper_generator/scripts/train_lora.py")
    else:
        print("학습 완료")
        print("Best checkpoint:", trainer.state.best_model_checkpoint)
        print("최종 LoRA adapter:", final_dir)
        print("학습 기록:", metrics_path)
    print("=" * 70)


if __name__ == "__main__":
    main()
