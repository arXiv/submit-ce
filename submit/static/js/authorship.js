/* Client-side effects for authorship step
   Enables or disables proxy confirmation checkbox based on not-author radio button. */
var handle_not_author = function(e){ 
  var proxy_checkbox = document.getElementById("proxy");
  var not_author = document.getElementById("authorship-1");
  if( not_author.checked ){
    proxy_checkbox.disabled = false;
  }else{
    proxy_checkbox.checked = false;
    proxy_checkbox.disabled = true;
  }
}

window.addEventListener('DOMContentLoaded', (e) => {
  var author = document.getElementById("authorship-0");
  var not_author = document.getElementById("authorship-1");
  not_author.onchange = handle_not_author;
  author.onchange = handle_not_author;
  handle_not_author(0);
});
