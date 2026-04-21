(function(){
  const key = 'site_theme';
  const toggle = document.getElementById('theme-toggle');
  const endpoint = '/accounts/api/ui/theme/';

  const getCookie = (name) => {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  };
  
  const apply = (theme) => {
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
    if(toggle) toggle.textContent = theme === 'dark' ? '☀️' : '🌙';
  };
  
  // Initialize theme
  const getInitialTheme = () => {
    try {
      const saved = localStorage.getItem(key);
      if (saved) return saved;
    } catch(e) {}
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  };
  
  apply(getInitialTheme());

  // Sync with server-side preference (persists across server restarts).
  fetch(endpoint, {
    method: 'GET',
    credentials: 'same-origin',
    headers: {'Accept': 'application/json'},
    cache: 'no-store',
  })
    .then(r => r.json())
    .then(d => {
      if (d && d.ok && (d.theme === 'light' || d.theme === 'dark')) {
        try { localStorage.setItem(key, d.theme); } catch(e) {}
        apply(d.theme);
      }
    })
    .catch(() => {});

  const saveServerTheme = (theme) => {
    fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
        'Accept': 'application/json',
      },
      body: JSON.stringify({theme}),
    }).catch(() => {});
  };
  
  // Toggle handler
  if (toggle) {
    toggle.addEventListener('click', function(){
      const isDark = document.documentElement.classList.contains('theme-dark');
      const newTheme = isDark ? 'light' : 'dark';
      try { localStorage.setItem(key, newTheme); } catch(e) {}
      apply(newTheme);
      saveServerTheme(newTheme);
    });
  }
})();