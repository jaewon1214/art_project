import { useState } from "react";

import "./App.css";
import PaperForm from "./components/PaperForm";
import PaperResult from "./components/PaperResult";
import { generatePaper } from "./services/paperApi";

function App() {
  const [title, setTitle] = useState(
    "생성형 AI와 음악 창작의 저작권 및 창작자성"
  );
  const [topic, setTopic] = useState(
    "생성형 AI 음악 창작에서 저작권, 창작자성, 음성복제 및 AI 작곡과 관련된 주요 쟁점"
  );
  const [paper, setPaper] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    setLoading(true);
    setError("");
    setPaper(null);

    try {
      const result = await generatePaper(title.trim(), topic.trim());
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
            <p className="institution-label">MUSIC & AI RESEARCH</p>
            <h1>생성형 AI 음악 연구 지원 시스템</h1>
            <p className="header-description">
              근거 자료를 바탕으로 연구 주제별 논문 초안을 작성하고
              참고문헌을 함께 확인할 수 있습니다.
            </p>
          </div>
        </div>
      </header>

      <main className="main-content">
        <div className="workspace-grid">
          <aside className="control-panel">
            <div className="panel-heading">
              <h2>연구 입력</h2>
              <p>논문 제목과 연구 주제를 함께 입력해 주세요.</p>
            </div>

            <PaperForm
              title={title}
              setTitle={setTitle}
              topic={topic}
              setTopic={setTopic}
              onSubmit={handleGenerate}
              loading={loading}
            />

            <div className="writing-guide">
              <h3>작성 안내</h3>
              <ol>
                <li>입력한 논문 제목은 최종 결과에 그대로 사용됩니다.</li>
                <li>연구 주제는 근거 검색과 논문의 세부 내용 구성에 사용됩니다.</li>
                <li>생성된 초안에서 관련 근거와 참고문헌을 함께 확인할 수 있습니다.</li>
              </ol>
            </div>
          </aside>

          <section className="paper-workspace">
            <div className="workspace-heading">
              <div>
                <p className="workspace-kicker">연구 결과</p>
                <h2>논문 초안</h2>
              </div>
              <p className="workspace-description">
                생성 결과는 검토·수정을 위한 초안입니다.
              </p>
            </div>

            {!paper && !loading && !error && (
              <div className="empty-state">
                <div className="empty-document" aria-hidden="true">
                  <div className="document-title-line" />
                  <div className="document-line short" />
                  <div className="document-rule" />
                  <div className="document-line" />
                  <div className="document-line" />
                  <div className="document-line medium" />
                  <div className="document-line" />
                  <div className="document-line short" />
                </div>
                <h3>논문 제목과 연구 주제를 입력해 주세요.</h3>
                <p>논문을 생성하면 이 영역에 초안과 참고문헌이 표시됩니다.</p>
              </div>
            )}

            {loading && (
              <div className="loading-card">
                <div className="loader" aria-hidden="true" />
                <div>
                  <h3>논문 초안을 작성하고 있습니다.</h3>
                  <p>관련 자료를 검토하고 논문 구조와 인용을 정리하는 중입니다.</p>
                </div>
              </div>
            )}

            {error && (
              <div className="error-card">
                <strong>논문 생성에 실패했습니다.</strong>
                <p>{error}</p>
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
