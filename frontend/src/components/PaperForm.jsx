function PaperForm({
  topic,
  setTopic,
  length,
  setLength,
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

  return (
    <form className="paper-form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label htmlFor="topic">연구 주제</label>

        <textarea
          id="topic"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="예: 생성형 AI와 음악 창작의 저작권 및 창작자성"
          rows={4}
          disabled={loading}
        />
      </div>

      <div className="form-group">
        <label htmlFor="length">목표 논문 길이</label>

        <div className="length-input-row">
          <input
            id="length"
            type="number"
            min="1000"
            max="20000"
            step="500"
            value={length}
            onChange={(event) =>
              setLength(Number(event.target.value))
            }
            disabled={loading}
          />

          <span>자</span>
        </div>

        <p className="form-hint">
          1,000 ~ 20,000자 범위에서 설정할 수 있습니다.
        </p>
      </div>

      <button
        className="generate-button"
        type="submit"
        disabled={loading || !topic.trim()}
      >
        {loading ? "논문 생성 중..." : "논문 생성"}
      </button>
    </form>
  );
}

export default PaperForm;