(function(){
    if (!document.body) return;
    if (document.body.dataset.authenticated !== '1') return;
    if (document.getElementById('app-macro-fab') || document.getElementById('adm-macro-fab')) return;

    var role = document.body.dataset.userRole || 'user';
    var styleId = 'jobflex-global-macros-style';
    if (!document.getElementById(styleId)) {
        var style = document.createElement('style');
        style.id = styleId;
        style.textContent = [
            '.jf-macro-fab{position:fixed;right:22px;bottom:22px;width:56px;height:56px;border-radius:50%;border:none;background:var(--accent);color:#fff;font-size:24px;cursor:pointer;box-shadow:0 10px 28px rgba(0,0,0,.25);z-index:9300;transition:transform .12s,opacity .12s;}',
            '.jf-macro-fab:hover{transform:translateY(-2px);opacity:.92;}',
            '.jf-macro-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9350;display:flex;align-items:center;justify-content:center;padding:16px;}',
            '.jf-macro-modal{width:min(720px,96vw);max-height:90vh;overflow:auto;background:var(--surface);border:1.5px solid var(--card-border);border-radius:16px;padding:18px;box-shadow:0 18px 60px rgba(0,0,0,.30);}',
            '.jf-macro-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px;}',
            '.jf-macro-title{margin:0;font-size:18px;font-weight:700;color:var(--text);}',
            '.jf-macro-close{border:none;background:transparent;color:var(--text-secondary);font-size:22px;cursor:pointer;line-height:1;padding:4px 8px;border-radius:8px;}',
            '.jf-macro-close:hover{color:#e05252;background:rgba(224,82,82,.12);}',
            '.jf-macro-sub{margin:0 0 14px;font-size:13px;color:var(--text-secondary);}',
            '.jf-macro-list{display:grid;gap:10px;}',
            '.jf-macro-item{border:1.5px solid var(--card-border);border-radius:12px;padding:12px;background:var(--bg);display:grid;gap:8px;}',
            '.jf-macro-name{font-size:14px;font-weight:700;color:var(--text);}',
            '.jf-macro-desc{font-size:13px;color:var(--text-secondary);}',
            '.jf-macro-hint{font-size:12px;color:var(--text-secondary);display:flex;flex-wrap:wrap;gap:6px;align-items:center;}',
            '.jf-kbd{border:1px solid var(--card-border);border-bottom-width:2px;border-radius:6px;padding:2px 6px;font-size:11px;color:var(--text);background:var(--surface);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}',
            '.jf-macro-toast{position:fixed;right:22px;bottom:92px;z-index:9400;padding:10px 14px;border-radius:10px;background:rgba(18,22,28,.94);color:#fff;font-size:13px;box-shadow:0 12px 34px rgba(0,0,0,.24);opacity:0;pointer-events:none;transform:translateY(6px);transition:opacity .16s,transform .16s;}',
            '.jf-macro-toast.show{opacity:1;transform:translateY(0);}'
        ].join('');
        document.head.appendChild(style);
    }

    function go(url) {
        window.location.href = url;
    }

    var configs = {
        applicant: {
            title: 'Макросы соискателя',
            subtitle: 'Открой окно через /, затем используй цифры для перехода между основными разделами.',
            actions: [
                { key: '1', label: 'Профиль', desc: 'Открыть основной профиль.', run: function(){ go('/accounts/profile/?tab=profile'); } },
                { key: '2', label: 'Аналитика', desc: 'Открыть аналитику соискателя.', run: function(){ go('/accounts/profile/?tab=analytics'); } },
                { key: '3', label: 'Календарь', desc: 'Открыть календарь соискателя.', run: function(){ go('/accounts/profile/?tab=calendar'); } },
                { key: '4', label: 'Чаты', desc: 'Перейти в список чатов.', run: function(){ go('/accounts/chats/'); } },
                { key: '5', label: 'Вакансии', desc: 'Перейти к списку вакансий.', run: function(){ go('/'); } }
            ]
        },
        manager: {
            title: 'Макросы менеджера',
            subtitle: 'Открой окно через /, затем используй цифры для перехода к рабочим разделам.',
            actions: [
                { key: '1', label: 'Профиль', desc: 'Открыть вкладку профиля.', run: function(){ go('/accounts/profile/?tab=profile'); } },
                { key: '2', label: 'Аналитика', desc: 'Открыть аналитику вакансий и откликов.', run: function(){ go('/accounts/manager/analytics/'); } },
                { key: '3', label: 'Календарь', desc: 'Открыть календарь собеседований.', run: function(){ go('/accounts/profile/?tab=calendar'); } },
                { key: '4', label: 'Мои вакансии', desc: 'Открыть список своих вакансий.', run: function(){ go('/my/'); } },
                { key: '5', label: 'Создать вакансию', desc: 'Открыть форму создания новой вакансии.', run: function(){ go('/create/'); } },
                { key: '6', label: 'Чаты', desc: 'Перейти в список чатов с соискателями.', run: function(){ go('/accounts/chats/'); } },
                { key: '7', label: 'Правила сообщений', desc: 'Настройка уведомлений (Telegram / e-mail).', run: function(){ go('/accounts/message-rules/'); } }
            ]
        },
        admin: {
            title: 'Макросы администратора',
            subtitle: 'Открой окно через /, затем используй цифры для перехода к административным разделам.',
            actions: [
                { key: '1', label: 'Админ-панель', desc: 'Открыть внутреннюю админ-панель JobFlex.', run: function(){ go('/accounts/admin-panel/'); } },
                { key: '2', label: 'Профиль администратора', desc: 'Открыть профиль администратора.', run: function(){ go('/accounts/admin-profile/'); } },
                { key: '3', label: 'Django Admin', desc: 'Открыть стандартную админку Django.', run: function(){ go('/admin/'); } },
                { key: '4', label: 'Swagger', desc: 'Открыть Swagger UI.', run: function(){ go('/swagger/'); } },
                { key: '5', label: 'ReDoc', desc: 'Открыть ReDoc.', run: function(){ go('/redoc/'); } },
                { key: '6', label: 'Профиль', desc: 'Открыть основной профиль пользователя.', run: function(){ go('/accounts/profile/'); } }
            ]
        },
        user: {
            title: 'Макросы',
            subtitle: 'Открой окно через /, затем используй цифры для навигации.',
            actions: [
                { key: '1', label: 'Главная', desc: 'Открыть список вакансий.', run: function(){ go('/'); } },
                { key: '2', label: 'Профиль', desc: 'Открыть профиль.', run: function(){ go('/accounts/profile/'); } },
                { key: '3', label: 'Чаты', desc: 'Открыть список чатов.', run: function(){ go('/accounts/chats/'); } }
            ]
        }
    };

    var config = configs[role] || configs.user;
    var overlay = document.createElement('div');
    overlay.id = 'jf-macro-overlay';
    overlay.className = 'jf-macro-overlay';
    overlay.style.display = 'none';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', config.title);

    var listHtml = config.actions.map(function(action){
        return '<div class="jf-macro-item">'
            + '<div class="jf-macro-name"><span class="jf-kbd">' + action.key + '</span> ' + action.label + '</div>'
            + '<div class="jf-macro-desc">' + action.desc + '</div>'
            + '</div>';
    }).join('');

    overlay.innerHTML = ''
        + '<div class="jf-macro-modal">'
        + '  <div class="jf-macro-head">'
        + '    <h3 class="jf-macro-title">' + config.title + '</h3>'
        + '    <button id="jf-macro-close" class="jf-macro-close" aria-label="Закрыть">×</button>'
        + '  </div>'
        + '  <p class="jf-macro-sub">' + config.subtitle + ' <span class="jf-kbd">Esc</span> закрыть окно.</p>'
        + '  <div class="jf-macro-list">' + listHtml + '</div>'
        + '</div>';

    var fab = document.createElement('button');
    fab.id = 'jf-macro-fab';
    fab.className = 'jf-macro-fab';
    fab.type = 'button';
    fab.title = config.title;
    fab.setAttribute('aria-label', config.title);
    fab.textContent = '?';

    var toast = document.createElement('div');
    toast.id = 'jf-macro-toast';
    toast.className = 'jf-macro-toast';
    toast.setAttribute('aria-live', 'polite');

    document.body.appendChild(fab);
    document.body.appendChild(overlay);
    document.body.appendChild(toast);

    var closeBtn = overlay.querySelector('#jf-macro-close');
    var toastTimer = null;

    function open(){ overlay.style.display = 'flex'; }
    function close(){ overlay.style.display = 'none'; }
    function toggle(){ if (overlay.style.display === 'none') open(); else close(); }
    function isOpen(){ return overlay.style.display !== 'none'; }
    function showToast(message){
        toast.textContent = message;
        toast.classList.add('show');
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function(){ toast.classList.remove('show'); }, 1400);
    }
    function runAction(index){
        var action = config.actions[index];
        if (!action) return;
        showToast(action.label);
        setTimeout(function(){ action.run(); }, 80);
    }

    fab.addEventListener('click', open);
    closeBtn.addEventListener('click', close);
    overlay.addEventListener('click', function(e){ if (e.target === overlay) close(); });

    document.addEventListener('keydown', function(e){
        if (e.key === 'Escape' && isOpen()) close();
    });

    document.addEventListener('keydown', function(e){
        if (e.ctrlKey || e.shiftKey || e.altKey || e.metaKey) return;
        var activeTag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
        var inField = activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select';
        var key = e.key || '';
        var code = e.code || '';

        if (!inField && (key === '/' || code === 'Slash' || code === 'NumpadDivide')) {
            e.preventDefault();
            toggle();
            return;
        }

        if (!isOpen() || inField) return;

        var index = -1;
        if (code.indexOf('Digit') === 0 || code.indexOf('Numpad') === 0) {
            var n = code.replace('Digit', '').replace('Numpad', '');
            index = parseInt(n, 10) - 1;
        } else if (/^[1-9]$/.test(key)) {
            index = parseInt(key, 10) - 1;
        }

        if (index >= 0) {
            e.preventDefault();
            runAction(index);
        }
    });
})();