function PaperForm({
  title,
  setTitle,
  topic,
  setTopic,
  onSubmit,
  loading,
}) {
  const handleSubmit = (event) => {
    event.preventDefault();

    if (!title.trim() || !topic.trim()) {
      return;
    }

    onSubmit();
  };

  return (
    <form className="paper-form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label htmlFor="title">논문 제목</label>
        <textarea
          id="title"
          className="title-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="예: 생성형 AI 학습데이터로서 음악저작물 이용의 공정이용 판단기준 연구"
          rows={3}
          disabled={loading}
        />
        <p className="form-help">
          입력한 제목은 최종 논문의 제목으로 그대로 사용됩니다.
        </p>
      </div>

      <div className="form-group">
        <label htmlFor="topic">연구 주제</label>
        <textarea
          id="topic"
          className="topic-input"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="예: 생성형 AI의 음악 학습데이터 이용과 공정이용 판단 요소를 중심으로 분석"
          rows={5}
          disabled={loading}
        />
        <p className="form-help">
          연구 주제는 근거 검색과 논문의 세부 내용 구성에 사용됩니다.
        </p>
      </div>

      <button
        className="generate-button"
        type="submit"
        disabled={loading || !title.trim() || !topic.trim()}
      >
        {loading ? "작성 중..." : "논문 초안 작성"}
      </button>
    </form>
  );
}

export default PaperForm;
