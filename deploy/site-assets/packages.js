/* Filters the package cards as you type. The list is complete without this file. */
(function () {
  "use strict";
  var input = document.getElementById("filter");
  var list = document.getElementById("packages");
  if (!input || !list) return;
  var cards = Array.prototype.slice.call(list.querySelectorAll(".card"));
  input.addEventListener("input", function () {
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    cards.forEach(function (card) {
      var text = card.textContent.toLowerCase();
      card.hidden = !words.every(function (word) { return text.indexOf(word) !== -1; });
    });
  });
})();
