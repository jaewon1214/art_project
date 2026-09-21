function cleanHeading(heading = "") {
  return heading
    .replace(/^\s*\d+\s*[.)]\s*/, "")
    .replace(/^\s*\d+\s+/, "")
    .trim();
}

function PaperSection({
  section,
  index,
  referenceNumberMap,
  formatPaperText,
}) {
  const originalContent = section.content || "";
  const visibleContent = formatPaperText(
    originalContent,
    referenceNumberMap
  );

  const trailingCitationNumbers = Array.from(
    new Set(
      (section.citations || [])
        .filter((sourceId) => {
          if (!referenceNumberMap.has(sourceId)) {
            return false;
          }

          return !originalContent.includes(`[${sourceId}]`);
        })
        .map((sourceId) => referenceNumberMap.get(sourceId))
    )
  );

  const heading = cleanHeading(section.heading);

  return (
    <section className="paper-section">
      <h2 className="paper-section-heading">
        <span>{index + 1}.</span> {heading}
      </h2>

      <p className="section-content">
        {visibleContent}
        {trailingCitationNumbers.length > 0 && (
          <span className="section-citations">
            {" "}
            {trailingCitationNumbers
              .map((number) => `[${number}]`)
              .join(" ")}
          </span>
        )}
      </p>
    </section>
  );
}

export default PaperSection;
