import html2canvas from "html2canvas";
import { jsPDF } from "jspdf";

const A4_WIDTH_MM = 210;
const A4_HEIGHT_MM = 297;
const PDF_MARGIN_MM = 12;
const PDF_CONTENT_WIDTH_MM = A4_WIDTH_MM - PDF_MARGIN_MM * 2;
const PDF_CONTENT_HEIGHT_MM = A4_HEIGHT_MM - PDF_MARGIN_MM * 2;

function sanitizeFileName(value, fallback = "paper") {
  const safe = (value || fallback)
    .replace(/[\\/:*?"<>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  return (safe || fallback).slice(0, 90);
}

async function waitForFonts() {
  if (document.fonts?.ready) {
    try {
      await document.fonts.ready;
    } catch {
      // 폰트 로딩 실패가 PDF 생성 자체를 막지는 않도록 한다.
    }
  }
}

function createCaptureRoot(sourceElement, mode) {
  const root = document.createElement("div");
  root.className = "pdf-capture-root";

  const clone = sourceElement.cloneNode(true);
  clone.removeAttribute("id");
  clone.classList.add("pdf-capture-document");

  if (mode === "abstract") {
    clone
      .querySelectorAll(
        ".paper-sections, .conclusion-section, .references-section"
      )
      .forEach((element) => element.remove());
  }

  root.appendChild(clone);
  document.body.appendChild(root);

  return { root, clone };
}

async function renderElementToCanvas(element) {
  await waitForFonts();

  return html2canvas(element, {
    scale: 2,
    useCORS: true,
    backgroundColor: "#fffefb",
    logging: false,
    windowWidth: element.scrollWidth,
    windowHeight: element.scrollHeight,
  });
}

function appendCanvasPages(pdf, canvas) {
  const pageHeightPx = Math.floor(
    canvas.width * (PDF_CONTENT_HEIGHT_MM / PDF_CONTENT_WIDTH_MM)
  );

  let offsetY = 0;
  let pageIndex = 0;

  while (offsetY < canvas.height) {
    const sliceHeight = Math.min(
      pageHeightPx,
      canvas.height - offsetY
    );

    const pageCanvas = document.createElement("canvas");
    pageCanvas.width = canvas.width;
    pageCanvas.height = sliceHeight;

    const context = pageCanvas.getContext("2d");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, pageCanvas.width, pageCanvas.height);
    context.drawImage(
      canvas,
      0,
      offsetY,
      canvas.width,
      sliceHeight,
      0,
      0,
      canvas.width,
      sliceHeight
    );

    if (pageIndex > 0) {
      pdf.addPage();
    }

    const sliceHeightMm =
      (sliceHeight * PDF_CONTENT_WIDTH_MM) / canvas.width;

    pdf.addImage(
      pageCanvas.toDataURL("image/jpeg", 0.96),
      "JPEG",
      PDF_MARGIN_MM,
      PDF_MARGIN_MM,
      PDF_CONTENT_WIDTH_MM,
      sliceHeightMm,
      undefined,
      "FAST"
    );

    offsetY += sliceHeight;
    pageIndex += 1;
  }
}

async function downloadFromPaperElement({
  sourceElement,
  title,
  mode,
}) {
  if (!sourceElement) {
    throw new Error("PDF로 변환할 논문 내용을 찾지 못했습니다.");
  }

  const { root, clone } = createCaptureRoot(sourceElement, mode);

  try {
    const canvas = await renderElementToCanvas(clone);
    const pdf = new jsPDF({
      orientation: "portrait",
      unit: "mm",
      format: "a4",
      compress: true,
    });

    appendCanvasPages(pdf, canvas);

    const prefix = mode === "abstract" ? "초록" : "논문";
    const fileName = `${prefix}_${sanitizeFileName(title)}.pdf`;
    pdf.save(fileName);
  } finally {
    root.remove();
  }
}

export async function downloadAbstractPdf(sourceElement, title) {
  return downloadFromPaperElement({
    sourceElement,
    title,
    mode: "abstract",
  });
}

export async function downloadFullPaperPdf(sourceElement, title) {
  return downloadFromPaperElement({
    sourceElement,
    title,
    mode: "full",
  });
}
