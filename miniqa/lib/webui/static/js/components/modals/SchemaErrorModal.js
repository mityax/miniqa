import {defineComponent} from 'vue';
import {state} from '../../state.js';
import {Icon} from '../Icon.js';

export const SchemaErrorModal = defineComponent({
  name: 'SchemaErrorModal',
  components: { Icon },

  setup() {
    function fix() {
      state.schemaError.visible = false;
    }
    function saveAnyway() {
      state.schemaError.visible = false;
      state.schemaError._onSaveAnyway?.();
    }
    return { state, fix, saveAnyway };
  },

  template: `
    <div id="schema-error-modal" class="overlay-screen" v-show="state.schemaError.visible">
      <div class="overlay-card" style="max-width:520px;text-align:left">
        <div style="display:flex;align-items:center;gap:var(--sp-3);margin-bottom:var(--sp-1)">
          <Icon name="alert-triangle" style="color:var(--c-warning);flex-shrink:0;width:18px;height:18px" />
          <h3 style="font-size:15px;font-weight:600;letter-spacing:-.02em">Schema validation errors</h3>
        </div>
        <p class="text-muted" style="font-size:12.5px;margin-bottom:var(--sp-4)">
          This YAML has schema violations. You can save anyway or go back to fix them.
        </p>
        <ul class="schema-error-list">
          <li
            v-for="(err, i) in state.schemaError.errors"
            :key="i"
            class="schema-error-item"
          >{{ err }}</li>
        </ul>
        <div class="modal-actions" style="margin-top:var(--sp-4)">
          <button class="btn-ghost"   @click="fix">Fix errors</button>
          <button class="btn-danger"  @click="saveAnyway">Save anyway</button>
        </div>
      </div>
    </div>`,
});

/** Imperatively show the schema error modal. */
export function showSchemaErrorModal(errors, onSaveAnyway) {
  state.schemaError.errors        = errors;
  state.schemaError._onSaveAnyway = onSaveAnyway;
  state.schemaError.visible       = true;
}
