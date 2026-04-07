import {computed, defineComponent, onMounted, onUnmounted, ref,} from 'vue';
import {state} from '../state.js';
import {send} from '../api.js';
import {computeTestProperties, formatDuration, jsyamlParse} from '../utils.js';
import {Icon} from './Icon.js';
import {StepList} from './StepList.js';

export const TestItem = defineComponent({
  name: 'TestItem',
  components: { Icon, StepList },

  props: {
    t: { type: Object, required: true },
  },

  emits: ['open-edit'],

  setup(props, { emit }) {
    const expanded = ref(false);

    // -- Derived display properties ---------------------------------------

    const props_ = computed(() => computeTestProperties(props.t, state.pipeline));

    const tc = computed(() => {
      try { return jsyamlParse(props.t.yaml); } catch { return null; }
    });

    const displayName = computed(() => tc.value?.name ?? props.t.stem);
    const fromSnap    = computed(() => tc.value?.from  ?? null);

    const statusDisplayText = computed(() => props_.value.failed ? 'failed' : props_.value.status)
    const itemClass = computed(() => {
      const { failed, succeeded, status } = props_.value;
      return [
        'test-item',
        failed    ? 'status-failed'  : '',
        succeeded ? 'status-success' : '',
        status === 'started' ? 'status-started' : '',
        expanded.value ? 'expanded' : '',
      ].filter(Boolean).join(' ');
    });

    const dotClass = computed(() => `test-status-dot ${props_.value.status}`);

    const progressPct = computed(() => {
      if (props_.value.curStep === null || !tc.value?.steps) return 0;
      return props_.value.curStep / tc.value.steps.length * 100;
    });

    // -- Live duration ticker ---------------------------------------------

    const liveDuration = ref(null);
    let   _ticker      = null;

    function updateDuration() {
      const { duration, status } = computeTestProperties(props.t, state.pipeline);
      if (status !== 'started') { liveDuration.value = null; return; }
      liveDuration.value = duration;
      _ticker = setTimeout(updateDuration, 300);
    }

    onMounted(updateDuration);
    onUnmounted(() => clearTimeout(_ticker));

    const displayDuration = computed(() => {
      const d = liveDuration.value ?? props_.value.duration;
      return d != null ? formatDuration(d) : '';
    });

    // -- Checkbox ---------------------------------------------------------

    const checked = computed({
      get: () => state.selectedStems.includes(props.t.stem),
      set: (v) => {
        if (v) {
          if (!state.selectedStems.includes(props.t.stem))
            state.selectedStems.push(props.t.stem);
        } else {
          const idx = state.selectedStems.indexOf(props.t.stem);
          if (idx !== -1) state.selectedStems.splice(idx, 1);
        }
      },
    });

    // -- Actions ----------------------------------------------------------

    function toggleExpand(e) {
      if (e.target.closest('button, input')) return;
      expanded.value = !expanded.value;
    }

    function openEdit() { emit('open-edit', props.t.stem); }

    function deleteTest(e) {
      e.stopPropagation();
      if (confirm('Delete test? This cannot be undone.'))
        send('delete_test', { stem: props.t.stem });
    }

    return {
      expanded, props_, tc, displayName, fromSnap,
      statusDisplayText, itemClass, dotClass, displayDuration,
      checked, toggleExpand, openEdit, deleteTest,
      progressPct,
    };
  },

  template: `
    <div :class="itemClass" :data-stem="t.stem">
      <div class="test-item-progess-bar" :style="{ '--progress': progressPct + '%' }"></div>
      <div class="test-item-header" @click="toggleExpand">
        <Icon name="chevron-right" extra-class="test-expand-icon" />
        <input
          type="checkbox"
          class="test-checkbox"
          :data-stem="t.stem"
          v-model="checked"
          @click.stop
        />
        <span :class="dotClass"></span>
        <span class="test-name">{{ displayName }}</span>
        <div class="test-meta">
          <span v-if="fromSnap">from: {{ fromSnap }}</span>
          <span :class="'badge badge-' + props_.status">{{ statusDisplayText }}</span>
          <span class="test-duration">{{ displayDuration }}</span>
        </div>
        <button class="btn-ghost btn-sm" @click.stop="openEdit" title="Edit">
          <Icon name="edit-2" />
        </button>
        <button
          class="btn-icon btn-sm"
          title="Delete"
          style="color:var(--c-error)"
          @click="deleteTest"
        >
          <Icon name="trash-2" />
        </button>
      </div>

      <div class="test-item-body" v-show="expanded">
        <StepList
          :tc="tc"
          :result="props_.result"
          :cur-step="props_.curStep"
          :is-canceled="props_.status === 'canceled'"
        />
        <div
          v-if="props_.result?.message"
          class="test-message"
        >{{ props_.result.message }}</div>
      </div>
    </div>`,
});
