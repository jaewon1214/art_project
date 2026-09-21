import { useState } from "react";

import {
  downloadAbstractPdf,
  downloadFullPaperPdf,
} from "../utils/downloadPaperPdf";

function PdfDownloadButtons({ paperElementId, title }) {
  const [downloading, setDownloading] = useState("");
  const [error, setError] = useState("");

  const handleDownload = async (mode) => {
    if (downloading) {
      return;
    }

    setError("");
    setDownloading(mode);

    try {
      const sourceElement = document.getElementById(paperElementId);

      if (mode === "abstract") {
        await downloadAbstractPdf(sourceElement, title);
      } else {
        await downloadFullPaperPdf(sourceElement, title);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "PDF 다운로드 중 오류가 발생했습니다."
      );
    } finally {
      setDownloading("");
    }
  };

  return (
    <div className="paper-download-area">
      <div className="paper-download-actions">
        <button
          type="button"
          className="paper-download-button"
          onClick={() => handleDownload("abstract")}
          disabled={Boolean(downloading)}
        >
          {downloading === "abstract"
            ? "초록 PDF 생성 중..."
            : "초록 PDF 다운로드"}
        </button>

        <button
          type="button"
          className="paper-download-button secondary"
          onClick={() => handleDownload("full")}
          disabled={Boolean(downloading)}
        >
          {downloading === "full"
            ? "전체 PDF 생성 중..."
            : "전체 논문 PDF 다운로드"}
        </button>
      </div>

      {error && (
        <p className="paper-download-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default PdfDownloadButtons;
