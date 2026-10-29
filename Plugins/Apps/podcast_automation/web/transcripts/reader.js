(() => {
  const sessions = [...document.querySelectorAll('.session')];
  const search = document.querySelector('#search');
  const selectedButton = document.querySelector('#copy-selected');
  const all = document.querySelector('#select-visible');
  const feedback = document.querySelector('#feedback');
  let timer;
  const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
  const searchable = new Map(sessions.map(session => [session, normalize(session.querySelector('h2').textContent + '\n' + session.querySelector('pre').textContent)]));
  function status(text) { feedback.textContent = text; feedback.hidden = false; clearTimeout(timer); timer = setTimeout(() => feedback.hidden = true, 4000); }
  async function copy(text) {
    try {
      try { await navigator.clipboard.writeText(text); }
      catch {
        const area = document.createElement('textarea'); area.value = text; area.style.position = 'fixed'; area.style.opacity = '0'; document.body.append(area); area.select();
        const ok = document.execCommand('copy'); area.remove(); if (!ok) throw Error('A cópia foi bloqueada pelo navegador.');
      }
      status('Texto copiado.');
    } catch(error) { status(error.message); }
  }
  const text = session => session.querySelector('h2').textContent + '\n\n' + session.querySelector('pre').textContent;
  function update() {
    const selected = sessions.filter(s => s.querySelector('.selection').checked);
    const visible = sessions.filter(s => !s.hidden);
    selectedButton.disabled = !selected.length;
    document.querySelector('#selected-count').textContent = selected.length ? '(' + selected.length + ')' : '';
    all.checked = !!visible.length && visible.every(s => s.querySelector('.selection').checked);
    all.indeterminate = visible.some(s => s.querySelector('.selection').checked) && !all.checked;
  }
  search.addEventListener('input', () => {
    const query = normalize(search.value);
    sessions.forEach(session => {
      session.hidden = !searchable.get(session).includes(query);
      document.querySelector('[data-session="' + session.id + '"]').hidden = session.hidden;
    });
    document.querySelector('#count').textContent = sessions.filter(s => !s.hidden).length + ' / ' + sessions.length + ' sessões'; update();
  });
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', () => copy(text(document.getElementById(button.dataset.copy)))));
  document.querySelectorAll('.selection').forEach(box => box.addEventListener('change', update));
  all.addEventListener('change', () => { sessions.filter(s => !s.hidden).forEach(s => s.querySelector('.selection').checked = all.checked); update(); });
  selectedButton.addEventListener('click', () => copy(sessions.filter(s => s.querySelector('.selection').checked).map(text).join('\n\n' + '─'.repeat(40) + '\n\n')));
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) {document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.dataset.session === entry.target.id));} }), {rootMargin:'-80px 0px -65% 0px'});
    sessions.forEach(session => observer.observe(session));
  }
})();
