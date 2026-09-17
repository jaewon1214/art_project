from __future__ import annotations

import json
import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from paper_generator.generator import generate_draft


TEST_CASES = [
    {
        "id": "topic_01",
        "source": "AI음악_논문주제.txt",
        "category": "저작권/학습데이터",
        "topic": (
            "생성형 AI 학습데이터로서 음악저작물 이용의 공정이용 판단기준 연구 "
            "— Concord Music Group 외 v. Anthropic 사건을 중심으로"
        ),
    },
    {
        "id": "topic_02",
        "source": "AI음악_논문주제.txt",
        "category": "창작자성/비교법",
        "topic": (
            "AI 생성 음악의 저작물성 인정에 관한 비교법적 연구 "
            "— 미국·중국·한국 판례를 중심으로"
        ),
    },
    {
        "id": "topic_03",
        "source": "AI음악_논문주제.txt",
        "category": "음성복제/퍼블리시티권",
        "topic": (
            "AI 음성복제 시 목소리 데이터 제공계약의 해석과 퍼블리시티권 침해 판단 "
            "— 국내 AI보컬 가처분 사건을 중심으로"
        ),
    },
    {
        "id": "topic_04",
        "source": "AI음악_논문주제.txt",
        "category": "스타일모방/저작권",
        "topic": (
            "AI에 의한 음악적 스타일 모방과 저작권법의 보호범위 "
            "— SOCAN v. Suno 사건을 중심으로"
        ),
    },
    {
        "id": "question_01",
        "source": "generative_ai_music_creation_questions.txt",
        "category": "저작권/미국vs유럽",
        "topic": (
            "AI 작곡 모델이 학습 데이터로 사용한 저작물의 범위와 국가별 법적 해석"
            "(미국의 공정이용 vs 유럽의 TDM 및 저작권 침해 판결) 차이는 "
            "국내외 음악 산업의 수익 배분 모델에 어떤 실질적 영향 및 시사점을 미치는가?"
        ),
    },
    {
        "id": "question_02",
        "source": "generative_ai_music_creation_questions.txt",
        "category": "창작자성/기여도",
        "topic": (
            "AI 작곡 도구를 활용한 음악 제작 과정에서 인간의 실질적 기여도"
            "(Human Contribution)를 측정하기 위한 정량적·정성적 표준 가이드라인은 "
            "어떻게 설계되어야 하는가?"
        ),
    },
    {
        "id": "question_03",
        "source": "generative_ai_music_creation_questions.txt",
        "category": "음성복제/인격권",
        "topic": (
            "타인의 음성을 상업적으로 복제·합성하는 AI 보이스 문제에 대응해, "
            "아티스트의 음성을 독립적 권리(퍼블리시티권 및 인격권)로 보호하기 위한 "
            "법제도적 방안과 라이선싱 제도는 어떻게 구축되어야 하는가?"
        ),
    },
    {
        "id": "question_04",
        "source": "generative_ai_music_creation_questions.txt",
        "category": "플랫폼/유통",
        "topic": (
            "음원 플랫폼의 AI 생성 음악 식별 라벨링 기법 및 로열티 재배분 구조 개편이 "
            "전통적 음악 창작자의 권리 보호와 음원 유통 시장 생태계에 미치는 효과는 무엇인가?"
        ),
    },
]


def char_count(draft: dict) -> int:
    return sum(len(str(draft.get(k, ""))) for k in [
        "title", "abstract", "introduction", "body", "conclusion"
    ])


def main():
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "test_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []

    print("=" * 72)
    print("Transformer 개인 테스트 시작")
    print(f"테스트 수: {len(TEST_CASES)}")
    print("=" * 72)

    for i, case in enumerate(TEST_CASES, start=1):
        print(f"\n[{i}/{len(TEST_CASES)}] {case['id']} / {case['category']}")
        print("주제:", case["topic"])

        started = time.time()

        try:
            draft = generate_draft(case["topic"])
            elapsed = round(time.time() - started, 2)

            result = {
                **case,
                "status": "ok",
                "elapsed_sec": elapsed,
                "total_chars": char_count(draft),
                "draft": draft,
            }

            print(f"완료: {elapsed}초 / {result['total_chars']}자")
            print("제목:", draft.get("title", "")[:120])

        except Exception as exc:
            elapsed = round(time.time() - started, 2)

            result = {
                **case,
                "status": "error",
                "elapsed_sec": elapsed,
                "error": repr(exc),
            }

            print("ERROR:", repr(exc))

        results.append(result)

        # 중간 저장: 중간에 멈춰도 결과 보존
        (out_dir / "draft_test_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 사람이 보기 쉬운 txt도 생성
    text_lines = []

    for item in results:
        text_lines.append("=" * 80)
        text_lines.append(f"{item['id']} | {item['category']}")
        text_lines.append(f"INPUT: {item['topic']}")
        text_lines.append(f"STATUS: {item['status']}")

        if item["status"] == "ok":
            text_lines.append(
                f"TIME: {item['elapsed_sec']} sec | CHARS: {item['total_chars']}"
            )

            draft = item["draft"]

            for section in [
                "title",
                "abstract",
                "introduction",
                "body",
                "conclusion",
            ]:
                text_lines.append("")
                text_lines.append(f"[{section.upper()}]")
                text_lines.append(draft.get(section, ""))

        else:
            text_lines.append(f"ERROR: {item.get('error')}")

        text_lines.append("")

    (out_dir / "draft_test_results.txt").write_text(
        "\n".join(text_lines),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("테스트 완료")
    print("=" * 72)
    print(out_dir / "draft_test_results.json")
    print(out_dir / "draft_test_results.txt")


if __name__ == "__main__":
    main()
