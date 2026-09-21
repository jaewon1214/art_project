import PaperSection from "./PaperSection";
import ReferenceList from "./ReferenceList";

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function createReferenceNumberMap(references = []) {
  return new Map(
    references.map((reference, index) => [
      reference.source_id,
      index + 1,
    ])
  );
}

function formatPaperText(text, referenceNumberMap) {
  if (!text) {
    return "";
  }

  let formatted = text;

  referenceNumberMap.forEach((number, sourceId) => {
    if (!sourceId) {
      return;
    }

    const pattern = new RegExp(
      `\\[\\s*${escapeRegExp(sourceId)}\\s*\\]`,
      "g"
    );

    formatted = formatted.replace(pattern, `[${number}]`);
  });

  formatted = formatted.replace(
    /\[\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*\]/gi,
    ""
  );

  formatted = formatted.replace(/[ \t]+([.,!?;:])/g, "$1");
  return formatted.trim();
}

function PaperResult({ paper }) {
  if (!paper) {
    return null;
  }

  const references = paper.references || [];
  const referenceNumberMap = createReferenceNumberMap(references);

  return (
    <article className="paper-result">
      <header className="paper-header">
        <h1>{paper.title}</h1>
      </header>

      <section className="abstract-section">
        <h2>초록</h2>
        <p>
          {formatPaperText(
            paper.abstract,
            referenceNumberMap
          )}
        </p>
      </section>

      <div className="paper-sections">
        {paper.sections?.map((section, index) => (
          <PaperSection
            key={`${section.heading}-${index}`}
            section={section}
            index={index}
            referenceNumberMap={referenceNumberMap}
            formatPaperText={formatPaperText}
          />
        ))}
      </div>

      <section className="conclusion-section">
        <h2>결론</h2>
        <p>
          {formatPaperText(
            paper.conclusion,
            referenceNumberMap
          )}
        </p>
      </section>

      <ReferenceList references={references} />
    </article>
  );
}

export default PaperResult;
