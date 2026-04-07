import {defineComponent, nextTick, ref, watch} from 'vue';
import {state} from '../../state.js';

export const PromptModal = defineComponent({
  name: 'PromptModal',

  setup() {
    const inputEl = ref(null);
    const value   = ref('');

    watch(() => state.prompt.visible, async (visible) => {
      if (!visible) return;
      value.value = state.prompt.defaultValue;
      await nextTick();
      inputEl.value?.focus();
    });

    function ok() {
      const v = value.value.trim() || null;
      state.prompt.visible = false;
      state.prompt._resolve?.(v);
    }

    function cancel() {
      state.prompt.visible = false;
      state.prompt._resolve?.(null);
    }

    function onKey(e) {
      if (e.key === 'Enter')  ok();
      if (e.key === 'Escape') cancel();
    }

    return { state, value, inputEl, ok, cancel, onKey };
  },

  template: `
    <div id="prompt-modal" class="overlay-screen" v-show="state.prompt.visible">
      <div class="overlay-card">
        <h3>{{ state.prompt.title }}</h3>
        <p class="text-muted">{{ state.prompt.description }}</p>
        <input
          ref="inputEl"
          v-model="value"
          type="text"
          class="input-field"
          @keydown="onKey"
        />
        <div class="modal-actions">
          <button class="btn-ghost"   @click="cancel">Cancel</button>
          <button class="btn-primary" @click="ok">OK</button>
        </div>
      </div>
    </div>`,
});

/**
 * Imperatively open the prompt modal.
 * Returns a Promise that resolves with the user's input string or null.
 */
export function promptModal(title, description = '', defaultValue = '') {
  return new Promise(resolve => {
    state.prompt.title        = title;
    state.prompt.description  = description;
    state.prompt.defaultValue = defaultValue;
    state.prompt._resolve     = resolve;
    state.prompt.visible      = true;
  });
}
