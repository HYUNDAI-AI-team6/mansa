// 파일을 끌어서 업로드 영역 위로 가져가면 영역을 강조한다(.drop-wrap 에 dragover class).
// 끄는 동안에는 브라우저가 :hover 를 적용하지 않아서 CSS 만으로는 강조할 수 없다.
// Gradio 가 drag 이벤트를 stopPropagation 으로 막으므로 capture 단계에서 먼저 받는다.
(() => {
  const ZONE = ".drop-wrap";
  let active = null;

  const hasFiles = (event) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
  const clear = () => {
    active?.classList.remove("dragover");
    active = null;
  };

  // dragover 는 끄는 동안 계속 오므로, 지금 포인터 아래의 영역이 바뀌었을 때만 갱신한다.
  document.addEventListener(
    "dragover",
    (event) => {
      if (!hasFiles(event)) return;
      const zone = event.target.closest?.(ZONE) ?? null;
      if (zone === active) return;
      clear();
      if (zone) {
        zone.classList.add("dragover");
        active = zone;
      }
    },
    true,
  );
  // 창 밖으로 나가면 dragleave 의 relatedTarget 이 null 이다.
  document.addEventListener("dragleave", (event) => event.relatedTarget === null && clear(), true);
  document.addEventListener("drop", clear, true);
  document.addEventListener("dragend", clear, true);
})();
