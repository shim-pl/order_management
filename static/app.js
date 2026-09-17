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


// ──────────────────────────────────────────────
// 数量入力（.qty-input）: 四則演算の計算と3桁カンマ表示
// ──────────────────────────────────────────────
(function () {
  const ZEN_TO_HAN = {
    '０': '0', '１': '1', '２': '2', '３': '3', '４': '4',
    '５': '5', '６': '6', '７': '7', '８': '8', '９': '9',
    '＋': '+', '－': '-', '−': '-', '―': '-', 'ー': '-',
    '＊': '*', '×': '*', '／': '/', '÷': '/',
    '（': '(', '）': ')', '．': '.', '，': ',', '、': ',', '　': ' '
  };

  // 全角を半角に寄せ、カンマと空白を除去する
  function normalize(raw) {
    return String(raw)
      .replace(/./g, ch => ZEN_TO_HAN[ch] || ch)
      .replace(/[,\s]/g, '');
  }

  // 四則演算の再帰下降パーサ（eval/Function を使わないためCSPでも動作する）
  function evaluate(src) {
    const s = normalize(src);
    if (!s) return null;
    if (!/^[0-9+\-*/().]+$/.test(s)) throw new Error('使用できない文字が含まれています');

    let i = 0;
    function expr() {
      let v = term();
      while (s[i] === '+' || s[i] === '-') {
        const op = s[i++];
        const r = term();
        v = op === '+' ? v + r : v - r;
      }
      return v;
    }
    function term() {
      let v = factor();
      while (s[i] === '*' || s[i] === '/') {
        const op = s[i++];
        const r = factor();
        if (op === '/' && r === 0) throw new Error('0で割ることはできません');
        v = op === '*' ? v * r : v / r;
      }
      return v;
    }
    function factor() {
      if (s[i] === '+') { i++; return factor(); }
      if (s[i] === '-') { i++; return -factor(); }
      if (s[i] === '(') {
        i++;
        const v = expr();
        if (s[i] !== ')') throw new Error('括弧が閉じられていません');
        i++;
        return v;
      }
      const start = i;
      while (i < s.length && /[0-9.]/.test(s[i])) i++;
      if (start === i) throw new Error('式が正しくありません');
      const n = parseFloat(s.slice(start, i));
      if (!isFinite(n)) throw new Error('式が正しくありません');
      return n;
    }

    const result = expr();
    if (i !== s.length) throw new Error('式が正しくありません');
    if (!isFinite(result)) throw new Error('計算結果が正しくありません');
    return Math.round(result);
  }

  const withCommas = n => n.toLocaleString('en-US');

  // 入力欄の直後にヒント表示用の要素を用意する
  function hintFor(input) {
    let el = input.nextElementSibling;
    if (!el || !el.classList.contains('qty-hint')) {
      el = document.createElement('span');
      el.className = 'qty-hint';
      input.insertAdjacentElement('afterend', el);
    }
    return el;
  }

  // 入力中: 計算結果をその場でプレビューする
  function preview(input) {
    const hint = hintFor(input);
    const raw = input.value.trim();
    if (!raw) {
      hint.textContent = '';
      hint.classList.remove('error');
      input.classList.remove('qty-invalid');
      return;
    }
    try {
      const v = evaluate(raw);
      input.classList.remove('qty-invalid');
      hint.classList.remove('error');
      // 単なる数値の入力中はプレビュー不要（演算子がある時だけ表示）
      hint.textContent = /[+\-*/()]/.test(normalize(raw)) ? '= ' + withCommas(v) : '';
    } catch (e) {
      input.classList.add('qty-invalid');
      hint.classList.add('error');
      hint.textContent = e.message;
    }
  }

  // フォーカスを外した時: 計算を確定してカンマ区切りで表示する
  function commit(input) {
    const raw = input.value.trim();
    if (!raw) return;
    try {
      const v = evaluate(raw);
      if (v === null) return;
      input.value = withCommas(v);
      const hint = hintFor(input);
      hint.textContent = '';
      hint.classList.remove('error');
      input.classList.remove('qty-invalid');
    } catch (e) {
      /* 不正な式はそのまま残し、ヒントの表示を維持する */
    }
  }

  document.addEventListener('input', e => {
    if (e.target.classList && e.target.classList.contains('qty-input')) preview(e.target);
  });

  document.addEventListener('blur', e => {
    if (e.target.classList && e.target.classList.contains('qty-input')) commit(e.target);
  }, true);

  // Enter キーで送信する前に計算を確定させる
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('qty-input')) {
      commit(e.target);
    }
  });

  // 送信時: カンマを除いた整数に直してから送る
  document.addEventListener('submit', e => {
    const inputs = e.target.querySelectorAll('.qty-input');
    for (const input of inputs) {
      const raw = input.value.trim();
      if (!raw) continue;
      let v;
      try {
        v = evaluate(raw);
      } catch (err) {
        e.preventDefault();
        preview(input);
        input.focus();
        return;
      }
      if (v < 0) {
        e.preventDefault();
        const hint = hintFor(input);
        hint.classList.add('error');
        hint.textContent = 'マイナスの値は入力できません';
        input.classList.add('qty-invalid');
        input.focus();
        return;
      }
      input.value = String(v);
    }
  }, true);

  // 既存の値を読み込み時にカンマ区切りへ整形する
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.qty-input').forEach(commit);
  });
})();
