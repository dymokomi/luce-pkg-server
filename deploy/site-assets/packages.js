/* Searches the package cards as you type and hides a section with no matches.
 * The page is complete without this file. */
(function () {
  "use strict";
  var input = document.getElementById("filter");
  var sections = Array.prototype.slice.call(document.querySelectorAll("section.kind"));
  var empty = document.getElementById("no-results");
  if (!input || !sections.length) return;
  function apply() {
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    sections.forEach(function (section) {
      var visible = 0;
      Array.prototype.forEach.call(section.querySelectorAll(".card"), function (card) {
        var text = card.textContent.toLowerCase();
        var match = words.every(function (word) { return text.indexOf(word) !== -1; });
        card.hidden = !match;
        if (match) visible += 1;
      });
      section.hidden = visible === 0;
      shown += visible;
    });
    if (empty) empty.hidden = shown !== 0;
  }
  input.addEventListener("input", apply);
  if (input.value) apply();
})();
