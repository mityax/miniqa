import {defineComponent} from 'vue';
import {state} from '../state.js';
import {Icon} from './Icon.js';

export const Lightbox = defineComponent({
  name: 'Lightbox',
  components: { Icon },
  setup() {
    function hide()  { state.lightbox.visible = false; }
    function click(e){ if (e.target === e.currentTarget) hide(); }
    return { state, hide, click };
  },
  template: `
    <div id="lightbox" class="overlay-screen" v-show="state.lightbox.visible" @click="click">
      <div class="lightbox-inner">
        <img id="lightbox-img" :src="state.lightbox.src" alt="" />
        <button class="lightbox-close btn-icon" @click.stop="hide">
          <Icon name="x" />
        </button>
      </div>
    </div>`,
});
