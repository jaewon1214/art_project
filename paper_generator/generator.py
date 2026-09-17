from __future__ import annotations

import re
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


ROOT = Path(__file__).resolve().parent

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
ADAPTER_DIR = ROOT / "models" / "paper-qwen-lora" / "best_adapter"

MAX_TOTAL_CHARS = 4500

SYSTEM_PROMPT = (
    "You are an academic paper drafting model. "
    "Generate a structured academic draft for the requested section. "
    "Focus on academic structure, argument flow, and section purpose. "
    "Do not invent citations, references, URLs, DOI values, statistics, "
    "court cases, dates, or legal provisions."
)

SECTION_CONFIG = {
    "title": {
        "instruction": (
            "Write an academic paper title appropriate for the research topic. "
            "Output only the title."
        ),
        "max_new_tokens": 80,
        "char_limit": 120,
    },
    "abstract": {
        "instruction": (
            "Write the abstract. Present the research background, central issue, "
            "research purpose, and overall direction of the paper."
        ),
        "max_new_tokens": 260,
        "char_limit": 650,
    },
    "introduction": {
        "instruction": (
            "Write the introduction. Organize it as research background, "
            "problem statement, research necessity, and research purpose."
        ),
        "max_new_tokens": 420,
        "char_limit": 950,
    },
    "body": {
        "instruction": (
            "Write the main body. Develop two or three major arguments in a "
            "logical academic structure. Avoid unsupported concrete facts."
        ),
        "max_new_tokens": 760,
        "char_limit": 2000,
    },
    "conclusion": {
        "instruction": (
            "Write the conclusion. Summarize the main argument and present "
            "implications, limitations, and directions for future discussion."
        ),
        "max_new_tokens": 360,
        "char_limit": 800,
    },
}


def _clean_text(text: str) -> str:
    text = (text or "").strip()

    # 모델이 불필요하게 붙인 heading 제거
    text = re.sub(
        r"^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*\s*)?"
        r"(?:title|abstract|introduction|main body|body|conclusion)\s*[:：-]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # 명백한 URL / DOI 제거
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\bdoi\s*:\s*\S+", "", text, flags=re.IGNORECASE)

    # [1], [2-4] 형태 인용 제거
    text = re.sub(r"\[(?:\d+)(?:\s*[-–,]\s*\d+)*\]", "", text)

    # References 이후는 제거
    text = re.split(
        r"\b(?:references|bibliography)\s*[:：]?",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _trim(text: str, limit: int) -> str:
    text = _clean_text(text)

    if len(text) <= limit:
        return text

    cut = text[:limit]

    candidates = [
        cut.rfind(". "),
        cut.rfind("? "),
        cut.rfind("! "),
        cut.rfind("다. "),
    ]
    pos = max(candidates)

    if pos >= int(limit * 0.55):
        return cut[: pos + 1].strip()

    return cut.rstrip()


class PaperDraftGenerator:
    """
    Transformer/LoRA 초안 생성기.

    역할:
    - title / abstract / introduction / body / conclusion 초안 생성
    - 구조와 논리 전개 제공

    사실 검증, 최신 자료 반영, 인용 생성, 최종 한국어 정제는
    후단 RAG + LLM 단계에서 수행한다.
    """

    def __init__(self):
        if not ADAPTER_DIR.exists():
            raise FileNotFoundError(
                f"LoRA adapter를 찾을 수 없습니다: {ADAPTER_DIR}"
            )

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU가 인식되지 않습니다.")

        self.tokenizer = AutoTokenizer.from_pretrained(
            str(ADAPTER_DIR),
            trust_remote_code=True,
            use_fast=True,
        )

        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            dtype=torch.float16,
            device_map="cuda",
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )

        self.model = PeftModel.from_pretrained(
            base_model,
            str(ADAPTER_DIR),
        )

        self.model.eval()

    def _build_prompt(self, topic: str, section: str) -> str:
        cfg = SECTION_CONFIG[section]

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"{cfg['instruction']}\n\n"
                    f"Research topic:\n{topic}"
                ),
            },
        ]

        return self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    @torch.inference_mode()
    def _generate_section(self, topic: str, section: str) -> str:
        cfg = SECTION_CONFIG[section]
        prompt = self._build_prompt(topic, section)

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
        ).to("cuda")

        outputs = self.model.generate(
            **inputs,
            max_new_tokens=cfg["max_new_tokens"],
            do_sample=True,
            temperature=0.45,
            top_p=0.90,
            repetition_penalty=1.10,
            no_repeat_ngram_size=4,
            pad_token_id=self.tokenizer.eos_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )

        generated = outputs[0][inputs["input_ids"].shape[1]:]

        text = self.tokenizer.decode(
            generated,
            skip_special_tokens=True,
        )

        return _trim(text, cfg["char_limit"])

    def generate_draft(self, topic: str) -> dict:
        topic = (topic or "").strip()

        if not topic:
            raise ValueError("topic은 비어 있을 수 없습니다.")

        draft = {
            "title": self._generate_section(topic, "title").strip('"“”'),
            "abstract": self._generate_section(topic, "abstract"),
            "introduction": self._generate_section(topic, "introduction"),
            "body": self._generate_section(topic, "body"),
            "conclusion": self._generate_section(topic, "conclusion"),
        }

        # 최종 초안 전체 길이 제한
        total = sum(len(v) for v in draft.values())

        if total > MAX_TOTAL_CHARS:
            overflow = total - MAX_TOTAL_CHARS
            body_limit = max(800, len(draft["body"]) - overflow)
            draft["body"] = _trim(draft["body"], body_limit)

        return draft


_generator: PaperDraftGenerator | None = None


def get_generator() -> PaperDraftGenerator:
    global _generator

    if _generator is None:
        _generator = PaperDraftGenerator()

    return _generator


def generate_draft(topic: str) -> dict:
    """
    Backend 공개 인터페이스.

    반환 형식:
    {
        "title": str,
        "abstract": str,
        "introduction": str,
        "body": str,
        "conclusion": str
    }
    """
    return get_generator().generate_draft(topic)


if __name__ == "__main__":
    import json
    import sys

    topic = " ".join(sys.argv[1:]).strip()

    if not topic:
        topic = "생성형 AI 음악의 저작권 문제"

    result = generate_draft(topic)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
