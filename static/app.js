/**
 * Alpine.js dashboard component for the SaaS Incident Monitor.
 * Handles: data fetching, auto-refresh, service grid, incident feed,
 * and the slide-in Service Registry drawer with full CRUD.
 */

function dashboard() {
  return {
    // ── State ──────────────────────────────────────────────────────────────
    health: {
      overall_score: 100,
      active_incident_count: 0,
      total_services: 0,
      enabled_services: 0,
      ai_analysis: '',
      ai_analysis_at: '',
      last_updated: '',
    },
    allServices: [],      // all services (for drawer)
    incidents: [],        // active incidents (for feed)
    selectedService: null,
    loading: false,
    refreshing: false,
    autoRefresh: true,
    _refreshTimer: null,
    lastRefreshLabel: 'Never',

    // Filters
    filterStatus: '',
    filterCategory: '',
    searchQuery: '',
    allCategories: [],

    // Drawer
    drawerOpen: false,
    showForm: false,
    editingSlug: null,
    savingForm: false,
    formError: '',
    categories: [],
    form: {
      name: '',
      api_url: '',
      category: 'Other',
      website: '',
      logo_url: '',
      poll_interval_minutes: 5,
      enabled: true,
      page_type: 'statuspage_v2',
    },

    // Theme
    darkMode: document.documentElement.classList.contains('dark'),

    // Toast
    toast: { show: false, message: '', type: 'success' },

    // Collapsed state for incident groups (slug → true means collapsed)
    collapsedGroups: {},

    // ── Computed ────────────────────────────────────────────────────────────
    get filteredServices() {
      return this.allServices.filter(s => {
        const matchStatus   = !this.filterStatus   || s.current_status === this.filterStatus;
        const matchCategory = !this.filterCategory || s.category === this.filterCategory;
        const matchSearch   = !this.searchQuery    ||
          s.name.toLowerCase().includes(this.searchQuery.toLowerCase()) ||
          s.category.toLowerCase().includes(this.searchQuery.toLowerCase());
        return matchStatus && matchCategory && matchSearch;
      });
    },

    get serviceIncidents() {
      if (!this.selectedService) return [];
      return this.incidents.filter(i => i.service_slug === this.selectedService.slug);
    },

    get healthLabel() {
      const s = this.health.overall_score;
      if (s >= 95) return 'Healthy';
      if (s >= 70) return 'Degraded';
      if (s >= 30) return 'Impacted';
      return 'Critical';
    },

    get healthColor() {
      const s = this.health.overall_score;
      if (s >= 95) return '#22c55e';
      if (s >= 70) return '#eab308';
      if (s >= 30) return '#f97316';
      return '#ef4444';
    },

    get healthColorText() {
      const s = this.health.overall_score;
      if (s >= 95) return 'text-green-400';
      if (s >= 70) return 'text-yellow-400';
      if (s >= 30) return 'text-orange-400';
      return 'text-red-400';
    },

    get affectedCategories() {
      const cats = new Set(this.incidents.map(i => i.service_category));
      return cats.size;
    },

    get groupedIncidents() {
      const severityLabels = { 1: 'Critical', 2: 'Major', 3: 'Minor', 4: 'Info' };
      const groups = {};
      for (const inc of this.incidents) {
        if (!groups[inc.service_slug]) {
          groups[inc.service_slug] = {
            slug: inc.service_slug,
            name: inc.service_name,
            logo_url: inc.logo_url || '',
            category: inc.service_category,
            worstSeverity: inc.severity,
            incidents: [],
          };
        }
        groups[inc.service_slug].incidents.push(inc);
        if (inc.severity < groups[inc.service_slug].worstSeverity) {
          groups[inc.service_slug].worstSeverity = inc.severity;
        }
      }
      return Object.values(groups)
        .sort((a, b) => a.worstSeverity - b.worstSeverity)
        .map(g => ({ ...g, worstSeverityLabel: severityLabels[g.worstSeverity] || 'Info' }));
    },

    // ── Init ────────────────────────────────────────────────────────────────
    async init() {
      await this.loadCategories();
      await this.fetchAll();
      this.startAutoRefresh();
    },

    // ── Data fetching ───────────────────────────────────────────────────────
    async fetchAll() {
      this.loading = true;
      try {
        await Promise.all([
          this.fetchHealth(),
          this.fetchServices(),
          this.fetchIncidents(),
        ]);
        this.lastRefreshLabel = 'Just now';
        this._updateRefreshLabel();
      } finally {
        this.loading = false;
      }
    },

    async fetchHealth() {
      try {
        const r = await fetch('/api/health');
        if (r.ok) this.health = await r.json();
      } catch { /* silent */ }
    },

    async fetchServices() {
      try {
        const r = await fetch('/api/services');
        if (r.ok) {
          this.allServices = await r.json();
          // Build category list for filters
          const cats = [...new Set(this.allServices.map(s => s.category))].sort();
          this.allCategories = cats;
        }
      } catch { /* silent */ }
    },

    async fetchIncidents() {
      try {
        const r = await fetch('/api/incidents?active=true');
        if (r.ok) {
          this.incidents = await r.json();
          this.collapseAllGroups();
        }
      } catch { /* silent */ }
    },

    async loadCategories() {
      try {
        const r = await fetch('/api/categories');
        if (r.ok) this.categories = await r.json();
      } catch {
        this.categories = ['CDN','Monitoring','Communication','Payments','Development',
                           'Storage','CRM','Security','Email','Infrastructure','Support','Other'];
      }
    },

    // ── Manual refresh ──────────────────────────────────────────────────────
    async manualRefresh() {
      if (this.refreshing) return;
      this.refreshing = true;
      try {
        const r = await fetch('/api/refresh', { method: 'POST' });
        if (r.ok) {
          const data = await r.json();
          this.showToast(`Refreshed ${data.services_fetched} service(s)`, 'success');
          await this.fetchAll();
        }
      } catch (e) {
        this.showToast('Refresh failed', 'error');
      } finally {
        this.refreshing = false;
      }
    },

    // ── Auto-refresh ────────────────────────────────────────────────────────
    startAutoRefresh() {
      if (this._refreshTimer) clearInterval(this._refreshTimer);
      if (!this.autoRefresh) return;
      this._refreshTimer = setInterval(() => this.fetchAll(), 60_000);
    },

    toggleAutoRefresh() {
      this.autoRefresh = !this.autoRefresh;
      if (this.autoRefresh) {
        this.startAutoRefresh();
        this.showToast('Auto-refresh enabled (60s)', 'success');
      } else {
        clearInterval(this._refreshTimer);
        this.showToast('Auto-refresh paused', 'success');
      }
    },

    _refreshStartTime: null,
    _updateRefreshLabel() {
      this._refreshStartTime = Date.now();
      const tick = () => {
        const elapsed = Math.floor((Date.now() - this._refreshStartTime) / 1000);
        if (elapsed < 60) this.lastRefreshLabel = `${elapsed}s ago`;
        else this.lastRefreshLabel = `${Math.floor(elapsed / 60)}m ago`;
      };
      if (this._labelTimer) clearInterval(this._labelTimer);
      this._labelTimer = setInterval(tick, 5000);
      tick();
    },

    // ── Service card selection ───────────────────────────────────────────────
    selectService(svc) {
      if (this.selectedService && this.selectedService.slug === svc.slug) {
        this.selectedService = null;
      } else {
        this.selectedService = svc;
        // Scroll to detail
        this.$nextTick(() => {
          const el = document.querySelector('[x-show="selectedService"]');
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
      }
    },

    // ── Drawer ──────────────────────────────────────────────────────────────
    openDrawer() {
      this.drawerOpen = true;
      this.showForm = false;
      this.editingSlug = null;
      this.formError = '';
    },

    closeDrawer() {
      this.drawerOpen = false;
      this.showForm = false;
      this.editingSlug = null;
      this.formError = '';
    },

    startAdd() {
      this.editingSlug = null;
      this.formError = '';
      this.form = {
        name: '',
        api_url: '',
        category: 'Other',
        website: '',
        logo_url: '',
        poll_interval_minutes: 5,
        enabled: true,
        page_type: 'statuspage_v2',
      };
      this.showForm = true;
      this.$nextTick(() => {
        const el = document.querySelector('[x-show="showForm"] input');
        if (el) el.focus();
      });
    },

    startEdit(svc) {
      this.editingSlug = svc.slug;
      this.formError = '';
      this.form = {
        name: svc.name,
        api_url: svc.api_url,
        category: svc.category || 'Other',
        website: svc.website || '',
        logo_url: svc.logo_url || '',
        poll_interval_minutes: svc.poll_interval_minutes || 5,
        enabled: svc.enabled !== false,
        page_type: svc.page_type || 'statuspage_v2',
      };
      this.showForm = true;
    },

    cancelForm() {
      this.showForm = false;
      this.editingSlug = null;
      this.formError = '';
    },

    async saveService() {
      this.formError = '';
      if (!this.form.name.trim()) { this.formError = 'Service name is required.'; return; }
      if (!this.form.api_url.trim()) { this.formError = 'Status page URL is required.'; return; }
      if (!this.form.api_url.startsWith('http')) { this.formError = 'URL must start with http:// or https://'; return; }

      this.savingForm = true;
      try {
        let url = '/api/services';
        let method = 'POST';
        if (this.editingSlug) {
          url = `/api/services/${this.editingSlug}`;
          method = 'PUT';
        }

        const r = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.form),
        });

        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          this.formError = err.detail || `Request failed (${r.status})`;
          return;
        }

        const saved = await r.json();
        this.showToast(
          this.editingSlug ? `"${saved.name}" updated` : `"${saved.name}" added`,
          'success'
        );
        this.cancelForm();
        await this.fetchServices();
        await this.fetchHealth();
      } catch (e) {
        this.formError = 'Network error. Is the server running?';
      } finally {
        this.savingForm = false;
      }
    },

    async deleteService(svc) {
      if (!confirm(`Delete "${svc.name}"? All associated incidents will also be removed.`)) return;
      try {
        const r = await fetch(`/api/services/${svc.slug}`, { method: 'DELETE' });
        if (r.ok || r.status === 204) {
          this.showToast(`"${svc.name}" deleted`, 'success');
          await this.fetchServices();
          await this.fetchIncidents();
          await this.fetchHealth();
          if (this.selectedService?.slug === svc.slug) this.selectedService = null;
        } else {
          this.showToast(`Failed to delete "${svc.name}"`, 'error');
        }
      } catch {
        this.showToast('Network error', 'error');
      }
    },

    async toggleService(svc) {
      try {
        const r = await fetch(`/api/services/${svc.slug}/toggle`, { method: 'PATCH' });
        if (r.ok) {
          const updated = await r.json();
          const idx = this.allServices.findIndex(s => s.slug === svc.slug);
          if (idx !== -1) this.allServices[idx] = updated;
          this.showToast(`"${svc.name}" ${updated.enabled ? 'enabled' : 'disabled'}`, 'success');
          await this.fetchHealth();
        }
      } catch {
        this.showToast('Toggle failed', 'error');
      }
    },

    // ── Helpers ─────────────────────────────────────────────────────────────
    scoreColor(score) {
      if (score >= 95) return 'text-green-400';
      if (score >= 70) return 'text-yellow-400';
      if (score >= 30) return 'text-orange-400';
      return 'text-red-400';
    },

    severityBadgeClass(severity) {
      const map = {
        1: 'bg-red-900/60 text-red-300',
        2: 'bg-orange-900/60 text-orange-300',
        3: 'bg-yellow-900/60 text-yellow-300',
        4: 'bg-blue-900/60 text-blue-300',
      };
      return map[severity] || map[4];
    },

    timeAgo(iso) {
      if (!iso) return '';
      const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
      if (diff < 60) return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    },

    showToast(message, type = 'success') {
      this.toast = { show: true, message, type };
      setTimeout(() => { this.toast.show = false; }, 3500);
    },

    // ── Incident groups ──────────────────────────────────────────────────────
    toggleGroup(slug) {
      this.collapsedGroups[slug] = !this.collapsedGroups[slug];
    },

    collapseAllGroups() {
      const collapsed = {};
      for (const g of this.groupedIncidents) collapsed[g.slug] = true;
      this.collapsedGroups = collapsed;
    },

    expandAllGroups() {
      this.collapsedGroups = {};
    },

    // ── Theme ────────────────────────────────────────────────────────────────
    toggleTheme() {
      this.darkMode = !this.darkMode;
      document.documentElement.classList.toggle('dark', this.darkMode);
      localStorage.setItem('theme', this.darkMode ? 'dark' : 'light');
    },
  };
}
