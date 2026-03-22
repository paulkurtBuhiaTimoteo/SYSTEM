function togglePassword(){
  const input = document.getElementById("password");
  const btn = document.querySelector(".toggle");
  if(!input || !btn) return;

  const isHidden = input.type === "password";
  input.type = isHidden ? "text" : "password";
  btn.textContent = isHidden ? "Hide" : "Show";
}