// 로딩 레이어가 떠 있는 화면의 나머지 내용을 inert 로 만든다.
// 눌러도 반응하지 않고 Tab 키로도 들어가지 못하게 하고, 레이어가 사라지면 되돌린다.
(function () {
  function sync() {
    document.querySelectorAll(".page").forEach(function (page) {
      var layer = page.querySelector(":scope > .busy-layer");
      var busy = !!layer && layer.offsetParent !== null && !!layer.querySelector(".busy-body");
      Array.prototype.forEach.call(page.children, function (child) {
        if (child === layer) return;
        if (busy) child.setAttribute("inert", "");
        else child.removeAttribute("inert");
      });
    });
  }
  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () {
      queued = false;
      sync();
    });
  }
  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "style", "hidden"],
  });
})();
