function PaperForm({
  topic,
  setTopic,
  inputType,
  setInputType,
  onSubmit,
  loading,
}) {
  const handleSubmit = (event) => {
    event.preventDefault();

    if (!topic.trim()) {
      return;
    }

    onSubmit();
  };

  const isTitleMode = inputType === "title";

  return (
    <form className="paper-form" onSubmit={handleSubmit}>
      <div className="input-type-group">
        <span className="input-type-label">입력 방식</span>
        <div className="input-type-selector" role="group" aria-label="입력 방식">
          <button
            type="button"
            className={`input-type-button ${
              inputType === "title" ? "active" : ""
            }`}
            onClick={() => setInputType("title")}
            disabled={loading}
          >
            제목
          </button>
          <button
            type="button"
            className={`input-type-button ${
              inputType === "topic" ? "active" : ""
            }`}
            onClick={() => setInputType("topic")}
            disabled={loading}
          >
            주제
          </button>
        </div>
      </div>

      <div className="form-group">
        <label htmlFor="topic">
          {isTitleMode ? "논문 제목" : "연구 주제"}
        </label>
        <textarea
          id="topic"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder={
            isTitleMode
              ? "예: 생성형 AI 학습데이터로서 음악저작물 이용의 공정이용 판단기준 연구"
              : "예: 생성형 AI 음악 학습데이터와 공정이용 문제"
          }
          rows={6}
          disabled={loading}
        />
        <p className="form-help">
          {isTitleMode
            ? "입력한 문구가 최종 논문의 제목으로 그대로 사용됩니다."
            : "입력한 주제를 바탕으로 논문에 적합한 제목을 자동으로 구성합니다."}
        </p>
      </div>

      <button
        className="generate-button"
        type="submit"
        disabled={loading || !topic.trim()}
      >
        {loading ? "작성 중..." : "논문 초안 작성"}
      </button>
    </form>
  );
}

export default PaperForm;
