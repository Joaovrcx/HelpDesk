// HelpDesk - Script principal
// Mantém aqui os comportamentos de front-end comuns a todas as páginas.

document.addEventListener("DOMContentLoaded", function () {
    // Atualiza automaticamente o ano exibido no rodapé
    var anoAtual = document.getElementById("ano-atual");
    if (anoAtual) {
        anoAtual.textContent = new Date().getFullYear();
    }
});
