import { useState } from "react";

import "./App.css";
import PaperForm from "./components/PaperForm";
import PaperResult from "./components/PaperResult";
import { generatePaper } from "./services/paperApi";

function App() {
  const [topic, setTopic] = useState(
    "생성형 AI와 음악 창작의 저작권 및 창작자성"
  );

  const [length, setLength] = useState(4500);

  const [paper, setPaper] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    setLoading(true);
    setError("");
    setPaper(null);

    try {
      const result = await generatePaper(
        topic.trim(),
        length
      );

      setPaper(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "알 수 없는 오류가 발생했습니다."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="top-header">
        <div className="top-header-inner">
          <div className="brand-mark">
            <span>AI</span>
          </div>

          <div className="brand-copy">
            <p className="service-label">
              AI MUSIC RESEARCH
            </p>

            <h1>
              생성형 AI 논문 작성 시스템
            </h1>

            <p className="header-description">
              RAG 기반 근거 검색과 Transformer 초안,
              LLM 검증을 결합하여 신뢰할 수 있는
              연구 논문 초안을 생성합니다.
            </p>
          </div>
        </div>
      </header>

      <main className="main-content">
        <div className="workspace-grid">
          <aside className="control-panel">
            <div className="panel-eyebrow">
              RESEARCH SETTINGS
            </div>

            <div className="panel-heading">
              <span className="panel-number">
                01
              </span>

              <div>
                <h2>연구 설정</h2>
                <p>
                  연구 주제와 목표 분량을 설정합니다.
                </p>
              </div>
            </div>

            <PaperForm
              topic={topic}
              setTopic={setTopic}
              length={length}
              setLength={setLength}
              onSubmit={handleGenerate}
              loading={loading}
            />

            <div className="pipeline-guide">
              <p className="pipeline-title">
                생성 과정
              </p>

              <div className="pipeline-step">
                <span>01</span>
                <div>
                  <strong>근거 자료 검색</strong>
                  <p>RAG 기반 관련 자료 탐색</p>
                </div>
              </div>

              <div className="pipeline-line" />

              <div className="pipeline-step">
                <span>02</span>
                <div>
                  <strong>논문 초안 생성</strong>
                  <p>Transformer 기반 구조 구성</p>
                </div>
              </div>

              <div className="pipeline-line" />

              <div className="pipeline-step">
                <span>03</span>
                <div>
                  <strong>근거 검증 및 정제</strong>
                  <p>LLM 기반 인용 및 문장 검증</p>
                </div>
              </div>
            </div>
          </aside>

          <section className="paper-workspace">
            <div className="workspace-heading">
              <div>
                <p className="workspace-label">
                  RESEARCH PAPER
                </p>

                <h2>논문 미리보기</h2>
              </div>

              <span className="target-length">
                목표 {length.toLocaleString()}자
              </span>
            </div>

            {!paper && !loading && !error && (
              <div className="empty-state">
                <div className="empty-document">
                  <div className="document-line line-title" />
                  <div className="document-line line-short" />

                  <div className="document-gap" />

                  <div className="document-line" />
                  <div className="document-line" />
                  <div className="document-line line-medium" />

                  <div className="document-gap" />

                  <div className="document-line" />
                  <div className="document-line line-short" />
                </div>

                <h3>
                  아직 생성된 논문이 없습니다.
                </h3>

                <p>
                  왼쪽에서 연구 주제를 설정한 뒤
                  논문 생성을 시작하세요.
                </p>
              </div>
            )}

            {loading && (
              <div className="loading-card">
                <div className="loader" />

                <div>
                  <p className="loading-label">
                    GENERATING PAPER
                  </p>

                  <h3>
                    논문을 생성하고 있습니다.
                  </h3>

                  <p>
                    근거 검색, 초안 구성 및
                    LLM 검증을 진행하고 있습니다.
                  </p>
                </div>
              </div>
            )}

            {error && (
              <div className="error-card">
                <div className="error-icon">
                  !
                </div>

                <div>
                  <strong>
                    논문 생성에 실패했습니다.
                  </strong>

                  <p>{error}</p>
                </div>
              </div>
            )}

            {paper && (
              <div className="result-wrapper">
                <PaperResult paper={paper} />
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;