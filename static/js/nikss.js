document.addEventListener("click",e=>{const nav=document.querySelector(".nav-links");if(nav&&nav.classList.contains("open")&&!e.target.closest(".nav") )nav.classList.remove("open");});
setTimeout(()=>document.querySelectorAll(".flash").forEach(x=>{setTimeout(()=>x.remove(),5000)}),500);
