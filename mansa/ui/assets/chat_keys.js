// 한글처럼 글자를 조합해서 쓰는 입력(IME) 중에 누른 엔터는 전송하지 않는다.
// 조합 중 엔터는 마지막 글자를 확정하는 키라서, 그대로 전송되면 마지막 글자가 어긋나거나 빠진다.
// Gradio 입력칸은 엔터를 keypress 로 받는다. 조합 중이었던 keydown 을 기억해 두었다가
// 같은 엔터의 keypress 가 Gradio 에 닿기 전에(capture) 막는다. 평소 엔터 전송은 Gradio 기본 동작에 맡긴다.
(() => {
  const SELECTOR = ".q-text textarea, .chat-text textarea";
  const inChatBox = (event) => event.target.matches?.(SELECTOR);
  let composingEnter = false;

  window.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Enter" && inChatBox(event)) {
        composingEnter = event.isComposing || event.keyCode === 229;
      }
    },
    true,
  );
  window.addEventListener(
    "keypress",
    (event) => {
      if (event.key === "Enter" && inChatBox(event) && (composingEnter || event.isComposing)) {
        event.stopImmediatePropagation();
      }
    },
    true,
  );
  window.addEventListener("keyup", () => (composingEnter = false), true);
})();
