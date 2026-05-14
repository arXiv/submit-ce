/* Client-side combobox for cross-list category selection on the Category step.
 *
 * Maintains two hidden form fields that the server controller consumes:
 *   - secondaries_staged_add:    set of categories to add on save
 *   - secondaries_staged_remove: set of saved categories to remove on save
 *
 * Both are comma-separated strings (see HiddenCategorySet in classification.py).
 *
 * The combobox wrapper carries a data-saved-categories JSON array of the
 * submission's currently-saved secondaries so the JS can correctly classify
 * a removal as "stage remove" vs. "un-stage add".
 *
 * Nothing is posted to the server until the user clicks Continue (action=next).
 */
(function () {
  var combobox = document.getElementById('combobox');
  if (!combobox) return;

  var input = document.getElementById('cross-list-input');
  var dropdown = document.getElementById('dropdown');
  var stagedAddField = document.getElementById('secondaries_staged_add');
  var stagedRemoveField = document.getElementById('secondaries_staged_remove');
  var maxTags = parseInt(combobox.dataset.maxTags, 10) || 4;

  var savedCategories;
  try {
    savedCategories = new Set(JSON.parse(combobox.dataset.savedCategories || '[]'));
  } catch (e) {
    savedCategories = new Set();
  }

  function parseSet(v) {
    return new Set((v || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean));
  }
  function getStagedAdd() { return parseSet(stagedAddField.value); }
  function getStagedRemove() { return parseSet(stagedRemoveField.value); }
  function serializeSet(s) { return Array.from(s).join(','); }
  function setStagedAdd(s) { stagedAddField.value = serializeSet(s); }
  function setStagedRemove(s) { stagedRemoveField.value = serializeSet(s); }

  function countTags() { return combobox.querySelectorAll('.tag').length; }

  function updateInputState() {
    var full = countTags() >= maxTags;
    if (full) {
      input.style.display = 'none';
      input.disabled = true;
      dropdown.style.display = 'none';
    } else {
      input.style.display = '';
      input.disabled = false;
    }
  }

  function findDropdownItem(value) {
    return dropdown.querySelector('.dropdown-item[data-value="' + CSS.escape(value) + '"]');
  }
  function hideDropdownOption(value) {
    var item = findDropdownItem(value);
    if (item) item.classList.add('is-taken');
  }
  function showDropdownOption(value) {
    var item = findDropdownItem(value);
    if (item) item.classList.remove('is-taken');
  }

  function addTag(value, display) {
    if (!value) return;
    if (countTags() >= maxTags) return;
    if (combobox.querySelector('.tag[data-value="' + CSS.escape(value) + '"]')) return;

    var stagedAdd = getStagedAdd();
    var stagedRemove = getStagedRemove();
    if (savedCategories.has(value)) {
      // Re-adding a saved cross-list that was staged for removal.
      stagedRemove.delete(value);
    } else {
      stagedAdd.add(value);
    }
    setStagedAdd(stagedAdd);
    setStagedRemove(stagedRemove);

    var tag = document.createElement('span');
    tag.className = 'tag';
    tag.dataset.value = value;
    // display is e.g. "cs.CR  Cryptography and Security" (two spaces from the form choice);
    // split on first run of whitespace to separate code from name.
    var match = display.match(/^(\S+)\s+(.*)$/);
    var code = match ? match[1] : value;
    var name = match ? match[2] : '';
    tag.innerHTML =
      '<span class="tag-code">' + code + '</span> ' +
      '<span class="tag-name">' + name + '</span> ' +
      '<button type="button" class="remove-tag" aria-label="Remove ' + code + '">&times;</button>';
    combobox.insertBefore(tag, input);

    hideDropdownOption(value);
    input.value = '';
    // Reset visibility of items hidden by typing filter (but not the already-taken ones)
    dropdown.querySelectorAll('.dropdown-item').forEach(function (i) {
      i.style.display = '';
    });
    updateInputState();
  }

  function removeTag(tagEl) {
    var value = tagEl.dataset.value;
    var stagedAdd = getStagedAdd();
    var stagedRemove = getStagedRemove();
    if (savedCategories.has(value)) {
      stagedRemove.add(value);
    } else {
      stagedAdd.delete(value);
    }
    setStagedAdd(stagedAdd);
    setStagedRemove(stagedRemove);

    tagEl.parentNode.removeChild(tagEl);
    showDropdownOption(value);
    updateInputState();
  }

  // Initial state: hide options for already-displayed pills.
  combobox.querySelectorAll('.tag').forEach(function (tag) {
    hideDropdownOption(tag.dataset.value);
  });
  updateInputState();

  combobox.addEventListener('click', function (e) {
    var removeBtn = e.target.closest('.remove-tag');
    if (removeBtn) {
      removeTag(removeBtn.parentElement);
      return;
    }
    if (countTags() < maxTags) {
      dropdown.style.display = 'block';
      input.focus();
    }
  });

  document.addEventListener('click', function (e) {
    if (!combobox.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = 'none';
    }
  });

  dropdown.addEventListener('click', function (e) {
    var item = e.target.closest('.dropdown-item');
    if (!item || item.classList.contains('is-taken')) return;
    addTag(item.dataset.value, item.textContent);
  });

  input.addEventListener('input', function (e) {
    var filter = e.target.value.toLowerCase();
    dropdown.style.display = 'block';
    dropdown.querySelectorAll('.dropdown-item').forEach(function (i) {
      if (i.classList.contains('is-taken')) {
        i.style.display = 'none';
        return;
      }
      var text = i.textContent.toLowerCase();
      i.style.display = text.indexOf(filter) !== -1 ? '' : 'none';
    });
  });

  input.addEventListener('focus', function () {
    if (countTags() < maxTags) dropdown.style.display = 'block';
  });
})();
