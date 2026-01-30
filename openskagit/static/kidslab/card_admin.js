(function () {
  const typeField = document.getElementById("id_card_type");
  if (!typeField) {
    return;
  }

  const typeFieldsets = Array.from(
    document.querySelectorAll("fieldset.card-type-fieldset")
  );

  function refreshFieldsets() {
    const value = typeField.value || "";
    const normalized = value.toUpperCase();

    typeFieldsets.forEach((fieldset) => {
      const classes = Array.from(fieldset.classList);
      const cardTypeClasses = classes.filter(
        (cls) => cls.startsWith("card-type-") && cls !== "card-type-fieldset"
      );
      const hasAll = cardTypeClasses.includes("card-type-all");
      const matchesCardType = cardTypeClasses.includes(`card-type-${normalized}`);
      fieldset.style.display = hasAll || matchesCardType ? "block" : "none";
    });
  }

  typeField.addEventListener("change", refreshFieldsets);
  refreshFieldsets();
})();
