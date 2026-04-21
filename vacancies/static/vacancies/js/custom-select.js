(function () {
    'use strict';

    function buildCustomSelect(nativeSelect) {
        // Skip already-hidden selects (manually managed, e.g. citizenship in register.html)
        if (nativeSelect.style.display === 'none') return;
        // Skip selects that opt out of custom styling (e.g. modal / inline forms)
        if (nativeSelect.hasAttribute('data-no-cs')) return;
        // Skip if already wrapped
        if (nativeSelect.previousElementSibling && nativeSelect.previousElementSibling.classList.contains('cs-trigger')) return;

        var options = Array.from(nativeSelect.options);
        var selectedIndex = nativeSelect.selectedIndex;
        var selectedOpt = options[selectedIndex] || null;
        var placeholder = (selectedOpt && selectedOpt.value === '') ? selectedOpt.text : (selectedOpt ? selectedOpt.text : '');
        var isPlaceholder = !selectedOpt || selectedOpt.value === '';

        // Build trigger
        var trigger = document.createElement('div');
        trigger.className = 'cs-trigger';
        trigger.setAttribute('tabindex', '0');
        trigger.setAttribute('role', 'combobox');
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');

        var valueSpan = document.createElement('span');
        valueSpan.className = 'cs-value' + (isPlaceholder ? ' cs-placeholder' : '');
        valueSpan.textContent = placeholder;

        var chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        chevron.setAttribute('class', 'cs-chevron');
        chevron.setAttribute('viewBox', '0 0 24 24');
        chevron.setAttribute('fill', 'none');
        chevron.setAttribute('stroke', 'currentColor');
        chevron.setAttribute('stroke-width', '2');
        var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M6 9l6 6 6-6');
        chevron.appendChild(path);

        trigger.appendChild(valueSpan);
        trigger.appendChild(chevron);

        // Build panel
        var panel = document.createElement('ul');
        panel.className = 'cs-panel';
        panel.setAttribute('role', 'listbox');

        var searchRow = document.createElement('li');
        searchRow.className = 'cs-search-row';
        var searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'cs-search-input';
        searchInput.placeholder = 'Начните вводить...';
        searchInput.setAttribute('aria-label', 'Поиск по списку');
        searchRow.appendChild(searchInput);
        panel.appendChild(searchRow);

        options.forEach(function (opt) {
            if (opt.value === '' && !opt.text.trim()) return; // skip empty placeholder option
            var li = document.createElement('li');
            li.className = 'cs-option';
            li.setAttribute('data-value', opt.value);
            li.textContent = opt.text;
            if (opt.selected && opt.value !== '') li.classList.add('cs-selected');
            panel.appendChild(li);
        });

        // Build wrapper
        var wrap = document.createElement('div');
        wrap.className = 'cs-wrap';

        // Insert wrap before native select, move native inside wrap
        nativeSelect.parentNode.insertBefore(wrap, nativeSelect);
        wrap.appendChild(trigger);
        wrap.appendChild(panel);
        wrap.appendChild(nativeSelect);

        // Hide native
        nativeSelect.style.display = 'none';

        // Logic
        function getItems() {
            return Array.from(panel.querySelectorAll('li.cs-option'));
        }

        function getVisibleItems() {
            return getItems().filter(function (el) { return el.style.display !== 'none'; });
        }

        function filterItems(query) {
            var needle = (query || '').trim().toLowerCase();
            getItems().forEach(function (el) {
                var hay = (el.textContent || '').toLowerCase();
                el.style.display = (!needle || hay.indexOf(needle) !== -1) ? '' : 'none';
            });
        }

        function clearFilter() {
            searchInput.value = '';
            filterItems('');
        }

        function open() {
            trigger.classList.add('cs-open');
            panel.classList.add('cs-open');
            trigger.setAttribute('aria-expanded', 'true');
            setTimeout(function () { searchInput.focus(); }, 0);
        }
        function close() {
            trigger.classList.remove('cs-open');
            panel.classList.remove('cs-open');
            trigger.setAttribute('aria-expanded', 'false');
            clearFilter();
        }
        function selectItem(li) {
            getItems().forEach(function (el) { el.classList.remove('cs-selected'); });
            li.classList.add('cs-selected');
            valueSpan.textContent = li.textContent;
            valueSpan.classList.remove('cs-placeholder');
            nativeSelect.value = li.getAttribute('data-value');
            // Trigger change event so any listeners fire (e.g. form auto-submit)
            nativeSelect.dispatchEvent(new Event('change', { bubbles: true }));
            close();
        }

        trigger.addEventListener('click', function () {
            trigger.classList.contains('cs-open') ? close() : open();
        });
        trigger.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); trigger.classList.contains('cs-open') ? close() : open(); }
            if (e.key === 'Escape') close();
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (!trigger.classList.contains('cs-open')) open();
                var visibleItems = getVisibleItems();
                var cur = panel.querySelector('.cs-selected') || visibleItems[0];
                var next = cur ? cur.nextElementSibling : visibleItems[0];
                while (next && next.style.display === 'none') next = next.nextElementSibling;
                if (next && next.classList.contains('cs-option')) { selectItem(next); next.scrollIntoView({ block: 'nearest' }); }
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                var cur2 = panel.querySelector('.cs-selected');
                var prev = cur2 ? cur2.previousElementSibling : null;
                while (prev && prev.style.display === 'none') prev = prev.previousElementSibling;
                if (prev && prev.classList.contains('cs-option')) { selectItem(prev); prev.scrollIntoView({ block: 'nearest' }); }
            }
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
                if (!trigger.classList.contains('cs-open')) open();
                searchInput.value += e.key;
                filterItems(searchInput.value);
            }
        });
        getItems().forEach(function (li) {
            li.addEventListener('click', function () { selectItem(li); });
        });
        searchInput.addEventListener('click', function (e) { e.stopPropagation(); });
        searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                close();
                trigger.focus();
                return;
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                var firstVisible = getVisibleItems()[0];
                if (firstVisible) selectItem(firstVisible);
                return;
            }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                var list = getVisibleItems();
                if (!list.length) return;
                var current = panel.querySelector('.cs-selected');
                var idx = current ? list.indexOf(current) : -1;
                if (e.key === 'ArrowDown') idx = Math.min(idx + 1, list.length - 1);
                else idx = Math.max(idx - 1, 0);
                if (idx >= 0) {
                    selectItem(list[idx]);
                    list[idx].scrollIntoView({ block: 'nearest' });
                }
                return;
            }
        });
        searchInput.addEventListener('input', function () {
            filterItems(searchInput.value);
        });
        document.addEventListener('click', function (e) {
            if (!wrap.contains(e.target)) close();
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('select').forEach(buildCustomSelect);
    });
})();