// 確認ダイアログ → フォーム送信
function confirmAction(message, form) {
  const overlay = document.getElementById('modal-overlay');
  const msgEl = document.getElementById('modal-message');
  const confirmBtn = document.getElementById('modal-confirm');
  const cancelBtn = document.getElementById('modal-cancel');

  msgEl.textContent = message;
  overlay.classList.remove('hidden');

  const close = () => overlay.classList.add('hidden');

  const onConfirm = () => { close(); form.submit(); confirmBtn.removeEventListener('click', onConfirm); };
  const onCancel = () => { close(); cancelBtn.removeEventListener('click', onCancel); };

  confirmBtn.addEventListener('click', onConfirm);
  cancelBtn.addEventListener('click', onCancel);
  overlay.addEventListener('click', e => { if (e.target === overlay) onCancel(); }, { once: true });
}
