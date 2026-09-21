const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

export async function generatePaper(topic, inputType = "topic") {
  const response = await fetch(`${API_BASE_URL}/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      topic,
      input_type: inputType,
    }),
  });

  if (!response.ok) {
    let message = "논문 생성 중 오류가 발생했습니다.";

    try {
      const errorData = await response.json();

      if (errorData?.error) {
        message = errorData.error;
      } else if (errorData?.detail) {
        if (typeof errorData.detail === "string") {
          message = errorData.detail;
        } else {
          message = "입력값을 확인해주세요.";
        }
      }
    } catch {
      // JSON 에러 응답이 아니면 기본 메시지를 사용한다.
    }

    throw new Error(message);
  }

  return response.json();
}