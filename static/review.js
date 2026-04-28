const form = document.querySelector(".review-form");
const allButton = document.querySelector('[data-action="select-all"]');
const noneButton = document.querySelector('[data-action="select-none"]');

function cutCheckboxes() {
  return Array.from(document.querySelectorAll('input[name="cut"]'));
}

allButton?.addEventListener("click", () => {
  cutCheckboxes().forEach((input) => {
    input.checked = true;
  });
});

noneButton?.addEventListener("click", () => {
  cutCheckboxes().forEach((input) => {
    input.checked = false;
  });
});

form?.addEventListener("submit", () => {
  const enabled = cutCheckboxes()
    .filter((input) => input.checked)
    .map((input) => input.value)
    .join(",");
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.name = "enabled_cuts";
  hidden.value = enabled;
  form.appendChild(hidden);
});
