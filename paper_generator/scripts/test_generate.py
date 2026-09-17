from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
ADAPTER_DIR = ROOT / "models" / "paper-qwen-lora" / "best_adapter"

SYSTEM_PROMPT = (
    "You are an academic paper drafting model. "
    "Write only the requested section in a formal academic style. "
    "Do not invent citations or references."
)

SECTION_PROMPTS = {
    "title": "주어진 연구 주제에 맞는 학술 논문 제목을 작성하시오.",
    "abstract": "주어진 연구 주제를 바탕으로 학술 논문의 초록을 작성하시오.",
    "introduction": (
        "주어진 연구 주제를 바탕으로 학술 논문의 서론을 작성하시오. "
        "연구 배경, 문제 제기, 연구 필요성이 자연스럽게 이어지도록 작성하시오."
    ),
    "body": (
        "주어진 연구 주제를 바탕으로 학술 논문의 본론을 작성하시오. "
        "핵심 논점과 근거를 논리적인 순서로 전개하시오."
    ),
    "conclusion": (
        "주어진 연구 주제를 바탕으로 학술 논문의 결론을 작성하시오. "
        "핵심 논의를 정리하고 연구의 의미와 시사점을 제시하시오."
    ),
}

def build_prompt(tokenizer, topic: str, section: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{SECTION_PROMPTS[section]}\n\nResearch topic:\n{topic}",
        },
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

def load_base():
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        trust_remote_code=True,
        use_fast=True,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.float16,
        device_map="cuda",
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    model.eval()
    return tokenizer, model

def load_lora():
    tokenizer = AutoTokenizer.from_pretrained(
        str(ADAPTER_DIR),
        trust_remote_code=True,
        use_fast=True,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    base = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.float16,
        device_map="cuda",
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base, str(ADAPTER_DIR))
    model.eval()
    return tokenizer, model

@torch.inference_mode()
def generate(tokenizer, model, topic: str, section: str, max_new_tokens: int) -> str:
    prompt = build_prompt(tokenizer, topic, section)
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")

    outputs = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
        repetition_penalty=1.08,
        pad_token_id=tokenizer.eos_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )

    generated = outputs[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--topic",
        type=str,
        default="생성형 AI 음악의 저작권 문제",
    )
    parser.add_argument(
        "--section",
        choices=["title", "abstract", "introduction", "body", "conclusion"],
        default="introduction",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Base Model과 LoRA 모델 출력을 비교",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU가 인식되지 않습니다.")

    if not ADAPTER_DIR.exists():
        raise FileNotFoundError(f"LoRA adapter를 찾을 수 없습니다: {ADAPTER_DIR}")

    limits = {
        "title": 80,
        "abstract": 300,
        "introduction": 500,
        "body": 700,
        "conclusion": 400,
    }
    max_new_tokens = limits[args.section]

    print("=" * 70)
    print("TOPIC:", args.topic)
    print("SECTION:", args.section)
    print("=" * 70)

    if args.compare:
        print("\n[BASE MODEL]")
        tokenizer, base_model = load_base()
        print(generate(tokenizer, base_model, args.topic, args.section, max_new_tokens))

        del base_model
        del tokenizer
        torch.cuda.empty_cache()

        print("\n" + "=" * 70)
        print("[LoRA MODEL]")
        tokenizer, lora_model = load_lora()
        print(generate(tokenizer, lora_model, args.topic, args.section, max_new_tokens))
    else:
        print("\n[LoRA MODEL]")
        tokenizer, model = load_lora()
        print(generate(tokenizer, model, args.topic, args.section, max_new_tokens))

if __name__ == "__main__":
    main()
