// vim: set ft=javascript ts=2 sw=2 et:
'use strict';

const { createApp, ref, reactive, onMounted } = Vue;

// ── Config ───────────────────────────────────────────────────────────────────
// Override by setting window.SWARM_API_BASE before this script loads.
const API_BASE = (window.SWARM_API_BASE || '').replace(/\/$/, '');

// ── API helper ───────────────────────────────────────────────────────────────
async function api(method, path, body = null, contentType = 'application/json') {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers['Content-Type'] = contentType;
    opts.body = typeof body === 'string' ? body : JSON.stringify(body);
  }
  const res = await fetch(API_BASE + path, opts);
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

// ── ReplicaBar component ─────────────────────────────────────────────────────
const ReplicaBar = {
  props: ['replicas'],
  computed: {
    desired() { return this.replicas?.desired ?? this.replicas?.expected ?? 0; },
    running() { return this.replicas?.running ?? this.replicas?.current  ?? 0; },
    pct()     {
      if (!this.desired) return 0;
      return Math.min(100, Math.round((this.running / this.desired) * 100));
    },
    fillClass() {
      if (this.running === 0)              return 'zero';
      if (this.running < this.desired)     return 'partial';
      return 'full';
    },
  },
  template: `
    <div class="replica-bar-wrap">
      <div class="replica-bar">
        <div class="replica-fill" :class="fillClass" :style="{width: pct + '%'}"></div>
      </div>
      <span>{{ running }}/{{ desired }}</span>
    </div>`,
};

// ── Main app ─────────────────────────────────────────────────────────────────
createApp({
  components: { ReplicaBar },

  setup() {
    const tab       = ref('stacks');
    const connected = ref(false);

    // ── Reactive data stores ──
    const stacks   = reactive({ loading: false, error: null, data: [] });
    const services = reactive({ loading: false, error: null, data: [] });

    // ── Modal state ──
    const modal = reactive({
      stackName:    '',
      serviceName:  '',
      scaleNum:     1,
      updateImage:  '',
      stackServices: { loading: false, error: null, data: [] },
      tasks:         { loading: false, error: null, data: [] },
    });

    // ── Toasts ──
    const toasts  = ref([]);
    let toastSeq  = 0;

    function toast(msg, type = 'secondary') {
      const id = ++toastSeq;
      toasts.value.push({ id, msg, type });
      setTimeout(() => removeToast(id), 4000);
    }
    function removeToast(id) {
      toasts.value = toasts.value.filter(t => t.id !== id);
    }

    // ── Bootstrap modal helpers ──
    function bsModal(id)      { return bootstrap.Modal.getOrCreateInstance(document.getElementById(id)); }
    function openModal(id)    { bsModal(id).show(); }
    function closeModal(id)   { bsModal(id).hide(); }

    // ── Connection check ──
    async function checkConnection() {
      try {
        await api('GET', '/stack');
        connected.value = true;
      } catch {
        connected.value = false;
      }
    }

    // ── Tab switching ──
    function switchTab(name) {
      tab.value = name;
      if (name === 'stacks')   loadStacks();
      if (name === 'services') loadServices();
    }

    // ── STACKS ──────────────────────────────────────────────────────────────

    async function loadStacks() {
      stacks.loading = true; stacks.error = null;
      try {
        stacks.data = await api('GET', '/stack');
      } catch (e) {
        stacks.error = e.message;
      } finally {
        stacks.loading = false;
      }
    }

    async function showStackServices(name) {
      modal.stackName = name;
      modal.stackServices.loading = true;
      modal.stackServices.error   = null;
      modal.stackServices.data    = [];
      openModal('modalStackServices');
      try {
        modal.stackServices.data = await api('GET', `/stack/${name}`);
      } catch (e) {
        modal.stackServices.error = e.message;
      } finally {
        modal.stackServices.loading = false;
      }
    }

    function confirmDeleteStack(name) {
      modal.stackName = name;
      openModal('modalDeleteStack');
    }

    async function deleteStack() {
      try {
        const r = await api('DELETE', `/stack/${modal.stackName}`);
        toast(`Stack "${modal.stackName}" deleted (${r.removed?.length ?? 0} services removed)`, 'success');
        closeModal('modalDeleteStack');
        loadStacks();
      } catch (e) {
        toast(e.message, 'danger');
      }
    }

    // ── SERVICES ────────────────────────────────────────────────────────────

    async function loadServices() {
      services.loading = true; services.error = null;
      try {
        services.data = await api('GET', '/service');
      } catch (e) {
        services.error = e.message;
      } finally {
        services.loading = false;
      }
    }

    async function showServiceTasks(name) {
      modal.serviceName = name;
      modal.tasks.loading = true;
      modal.tasks.error   = null;
      modal.tasks.data    = [];
      openModal('modalServiceTasks');
      try {
        modal.tasks.data = await api('GET', `/service/${name}`);
      } catch (e) {
        modal.tasks.error = e.message;
      } finally {
        modal.tasks.loading = false;
      }
    }

    function openScale(name, desired) {
      modal.serviceName = name;
      modal.scaleNum    = desired ?? 1;
      openModal('modalScale');
    }

    async function doScale() {
      const num = parseInt(modal.scaleNum, 10);
      if (isNaN(num) || num < 0) { toast('Invalid replica count', 'danger'); return; }
      try {
        await api('POST', `/service/${modal.serviceName}/scale/${num}`);
        toast(`"${modal.serviceName}" scaled to ${num}`, 'success');
        closeModal('modalScale');
        loadServices();
      } catch (e) {
        toast(e.message, 'danger');
      }
    }

    function openUpdate(name) {
      modal.serviceName = name;
      modal.updateImage = '';
      openModal('modalUpdate');
    }

    async function doUpdate() {
      const image = modal.updateImage.trim() || null;
      try {
        await api('POST', `/service/${modal.serviceName}/update`, { image });
        toast(`"${modal.serviceName}" update triggered`, 'success');
        closeModal('modalUpdate');
        loadServices();
      } catch (e) {
        toast(e.message, 'danger');
      }
    }

    async function doRollback(name) {
      try {
        await api('POST', `/service/${name}/rollback`);
        toast(`"${name}" rolled back`, 'warning');
        loadServices();
      } catch (e) {
        toast(e.message, 'danger');
      }
    }

    function confirmDeleteService(name) {
      modal.serviceName = name;
      openModal('modalDeleteService');
    }

    async function deleteService() {
      try {
        await api('DELETE', `/service/${modal.serviceName}`);
        toast(`Service "${modal.serviceName}" deleted`, 'success');
        closeModal('modalDeleteService');
        loadServices();
      } catch (e) {
        toast(e.message, 'danger');
      }
    }

    // ── Task state badge helper ──
    function taskStateBadge(state) {
      if (!state) return 'bg-secondary';
      switch (state.toLowerCase()) {
        case 'running':              return 'bg-success';
        case 'failed':
        case 'rejected':             return 'bg-danger';
        case 'starting':
        case 'preparing':
        case 'pending':              return 'bg-primary';
        case 'shutdown':
        case 'complete':             return 'bg-secondary';
        default:                     return 'bg-secondary';
      }
    }

    // ── Init ──
    onMounted(() => {
      checkConnection();
      loadStacks();
    });

    return {
      tab, connected,
      stacks, services, modal, toasts,
      switchTab,
      loadStacks, showStackServices, confirmDeleteStack, deleteStack,
      loadServices, showServiceTasks,
      openScale, doScale,
      openUpdate, doUpdate,
      doRollback,
      confirmDeleteService, deleteService,
      taskStateBadge, removeToast,
    };
  },
}).mount('#app');
