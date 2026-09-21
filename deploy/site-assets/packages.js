/* Searches the package cards as you type and hides a section with no matches.
 * The page is complete without this file. */
(function () {
  "use strict";
  var input = document.getElementById("filter");
  var sections = Array.prototype.slice.call(document.querySelectorAll("section.kind"));
  var empty = document.getElementById("no-results");
  var count = document.querySelector("p.count");
  if (!input || !sections.length) return;
  var total = count ? count.textContent : "";
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function apply() {
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    var found = {};
    sections.forEach(function (section) {
      var visible = 0;
      Array.prototype.forEach.call(section.querySelectorAll(".card"), function (card) {
        var text = card.textContent.toLowerCase();
        var match = words.every(function (word) { return text.indexOf(word) !== -1; });
        card.hidden = !match;
        if (match) visible += 1;
      });
      section.hidden = visible === 0;
      found[section.id] = visible;
      shown += visible;
    });
    if (empty) empty.hidden = shown !== 0;
    if (count) count.textContent = words.length === 0 ? total :
      plural(found.applications || 0, "application", "applications") + " \u00b7 " +
      plural(found.libraries || 0, "library", "libraries") + " match";
  }
  input.addEventListener("input", apply);
  if (input.value) apply();
})();
