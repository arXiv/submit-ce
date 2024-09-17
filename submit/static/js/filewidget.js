/**
  * Populate the upload selection widget with a filename.
  **/
var update_filename = function() {
    if(file.files.length > 0) {
        document.getElementById('filename').innerHTML = file.files[0].name;
        document.getElementById('file-submit').disabled = false;
    }
    else {
      document.getElementById('file-submit').disabled = true;
    }
};

/**
  * Bind the filename updater to the upload widget.
  **/
window.addEventListener('DOMContentLoaded', function() {
    var file = document.getElementById('file');
    file.onchange = update_filename;
});
