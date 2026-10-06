const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const openM = id => $('#' + id).classList.add('show');
const closeM = () => $$('.modal').forEach(m => m.classList.remove('show'));
$$('[data-close]').forEach(b => b.onclick = closeM);
$$('.modal').forEach(m => m.onclick = e => { if (e.target === m) closeM(); });
document.addEventListener('keydown', e => e.key === 'Escape' && closeM());

// الوضع الليلي/النهاري
$$('.themeBtn').forEach(b => b.onclick = () => {
  const d = document.documentElement, n = d.dataset.theme === 'dark' ? 'light' : 'dark';
  d.dataset.theme = n; localStorage.setItem('theme', n); document.dispatchEvent(new Event('themechange'));
});
if ($('#menuBtn')) $('#menuBtn').onclick = () => $('#sidebar').classList.toggle('open');

// نموذج الإضافة/التعديل (نافذة واحدة لكل صفحة)
const fm = $('#itemForm');
function openForm(item) {
  fm.reset(); fm.elements.id.value = item ? item.id : '';
  if (item) $$('input,select,textarea', fm).forEach(e => { if (e.name in item && e.name !== 'csrf_token') e.value = item[e.name]; });
  const h = $('#formTitle'); h.textContent = item ? h.dataset.edit : h.dataset.add; openM('m-form');
}
if (fm) {
  $$('[data-new]').forEach(b => b.onclick = () => openForm());
  $$('[data-item]').forEach(b => b.onclick = () => openForm(JSON.parse(b.dataset.item)));
}
// نافذة تأكيد الحذف
$$('[data-del]').forEach(b => b.onclick = () => {
  $('#delForm').action = b.dataset.del; $('#delName').textContent = b.dataset.name; openM('m-del');
});
