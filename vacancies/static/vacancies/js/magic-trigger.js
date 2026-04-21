(function(){
  // Trigger boingOutDown on vacancy card and show placeholder with title
  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('.vacancy-card').forEach(card => {
      const placeholder = card.querySelector('.vacancy-placeholder');
      if (!placeholder) return;

      // Trigger animation on click or keyboard activation (Enter / Space)
      const shouldIgnoreEvent = (evt) => {
        // don't trigger when clicking interactive controls inside the card
        if (evt && evt.target) {
          if (evt.target.closest && evt.target.closest('a, button, input, select, label')) return true;
        }
        return false;
      };

      const trigger = (evt) => {
        if (shouldIgnoreEvent(evt)) return;
        // if already replaced, do nothing
        if (card.classList.contains('card-hidden')) return;
        // restart animation
        card.classList.remove('magictime','boingOutDown');
        // small delay to force reflow
        setTimeout(() => card.classList.add('magictime','boingOutDown'), 8);
      };

      card.addEventListener('click', trigger);
      // keyboard support: Enter (13) and Space (32)
      card.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();
          trigger(ev);
        }
      });

      // When animation ends, show placeholder and hide other content
      card.addEventListener('animationend', (ev) => {
        // ensure this was the card animation
        if (card.classList.contains('card-hidden')) return;
        // ratings removed — do not populate rating into placeholder

        placeholder.classList.add('visible');
        card.classList.add('card-hidden');
        // remove animation classes so it can be re-triggered if needed
        card.classList.remove('magictime','boingOutDown');
      });

      // allow restoring card on placeholder click (handy for testing/mobile)
      placeholder.addEventListener('click', (e) => {
        // prevent the click from bubbling to the card (which would retrigger animation)
        e.stopPropagation();
        placeholder.classList.remove('visible');
        card.classList.remove('card-hidden');
      });
    });
  });
})();