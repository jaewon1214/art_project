function PaperForm({
  topic,
  setTopic,
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
        <label htmlFor="topic">주제 또는 연구 질문</label>
        <textarea
          id="topic"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="예: 생성형 AI 학습데이터로서 음악저작물 이용의 공정이용 판단기준 연구"
          rows={6}
          disabled={loading}
        />
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
