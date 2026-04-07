import {defineComponent, onMounted, onUnmounted, ref, watch,} from 'vue';
import {state} from '../state.js';
import {onApiEvent, send} from '../api.js';
import {insertOrCopy} from '../editor.js';
import {Icon} from './Icon.js';

export const RefsPanel = defineComponent({
  name: 'RefsPanel',
  components: { Icon },

  setup() {
    const sections = ref([]);

    async function refresh() {
      try {
        const resp = await fetch('/api/screenshots');
        const list = await resp.json();
        if (!list.length) { sections.value = []; return; }

        list.sort((a, b) =>
          a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
        );

        const stem       = state.edit.test_stem;
        const thisTest   = list.filter(p => p.startsWith(`${stem}/`));
        const general    = list.filter(p => !p.includes('/'));
        const otherTests = list.filter(p => !thisTest.includes(p) && !general.includes(p));

        sections.value = [
          thisTest.length   ? { name: 'This Test',   items: thisTest   } : null,
          general.length    ? { name: 'General',     items: general    } : null,
          otherTests.length ? { name: 'Other Tests', items: otherTests } : null,
        ].filter(Boolean);
      } catch {
        sections.value = [];
      }
    }

    // Re-fetch when user opens a different test
    watch(() => state.edit.test_stem, (stem) => { if (stem) refresh(); });

    let _unsub = null;
    onMounted(() => {
      refresh();
      _unsub = onApiEvent('refresh_refs', refresh);
    });
    onUnmounted(() => { _unsub?.(); });

    function displayName(path) { return path.replace(/\.[^.]+$/, ''); }

    function previewRef(path) {
      state.lightbox.src     = `/api/screenshot/${encodeURIComponent(path)}`;
      state.lightbox.visible = true;
    }

    function copyRef(path, e) {
      e.stopPropagation();
      insertOrCopy(displayName(path));
    }

    function deleteRef(path, e) {
      e.stopPropagation();
      if (confirm(`Delete '${path}'?`)) send('delete_screenshot', { path });
    }

    return { sections, refresh, previewRef, copyRef, deleteRef, displayName };
  },

  template: `
    <div id="refs-panel">
      <div class="refs-header">
        <span>Reference screenshots</span>
        <button class="btn-icon btn-sm" title="Refresh" @click="refresh">
          <Icon name="refresh-cw" />
        </button>
      </div>

      <div id="refs-list">
        <span
          v-if="!sections.length"
          style="color:var(--fg-subtle);font-size:12px"
        >No screenshots yet</span>

        <div v-for="sec in sections" :key="sec.name" class="refs-section">
          <div><h5>{{ sec.name }}</h5></div>
          <div class="refs-section-items-container">
            <div
              v-for="path in sec.items"
              :key="path"
              class="ref-item"
              title="Click to preview"
              @click="previewRef(path)"
            >
              <Icon name="image" style="color:var(--fg-muted)" />
              <span class="ref-item-name">{{ displayName(path) }}</span>
              <span style="flex-grow:1"></span>
              <button class="btn-icon btn-sm" title="Copy name" @click="copyRef(path, $event)">
                <Icon name="copy" />
              </button>
              <button
                class="btn-icon btn-sm" title="Delete"
                style="color:var(--c-error)"
                @click="deleteRef(path, $event)"
              >
                <Icon name="trash-2" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>`,
});
