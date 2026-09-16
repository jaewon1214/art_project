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
          <div>
            <p className="service-label">
              GENERATIVE AI RESEARCH
            </p>

            <h1>
              생성형 AI 논문 작성 시스템
            </h1>

            <p className="header-description">
              RAG 검색, Transformer 초안 생성,
              LangChain과 LLM 검증을 통해
              연구 논문 초안을 생성합니다.
            </p>
          </div>

          <div className="system-status">
            <span className="status-dot" />
            Backend Ready
          </div>
        </div>
      </header>

      <main className="main-content">
        <section className="generator-card">
          <div className="card-heading">
            <span>01</span>

            <div>
              <h2>연구 주제 설정</h2>

              <p>
                연구하고 싶은 주제와 목표 분량을
                입력하세요.
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
        </section>

        {loading && (
          <section className="loading-card">
            <div className="loader" />

            <div>
              <h2>논문을 생성하고 있습니다.</h2>

              <p>
                RAG 검색, 초안 생성 및 LLM 검증을
                진행하고 있습니다.
              </p>
            </div>
          </section>
        )}

        {error && (
          <section className="error-card">
            <strong>논문 생성 실패</strong>
            <p>{error}</p>
          </section>
        )}

        {paper && (
          <section className="result-wrapper">
            <div className="card-heading">
              <span>02</span>

              <div>
                <h2>생성 결과</h2>

                <p>
                  생성된 논문과 참고 출처를
                  확인할 수 있습니다.
                </p>
              </div>
            </div>

            <PaperResult paper={paper} />
          </section>
        )}
      </main>
    </div>
  );
}

export default App;