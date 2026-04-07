import {defineComponent} from 'vue';
import {state} from '../state.js';

export const ToastContainer = defineComponent({
  name: 'ToastContainer',
  setup() { return { state }; },
  template: `
    <div id="toasts">
      <div
        v-for="t in state.toasts"
        :key="t.id"
        :class="['toast', t.kind]"
      >{{ t.msg }}</div>
    </div>`,
});
