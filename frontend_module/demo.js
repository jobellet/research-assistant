const demoData = {
  nodes: [
    { id: "1", title: "The art of braking", authors: "Hooge et al.", year: "2015", cluster: 0, cluster_color: "#6366f1", x: -0.5, y: -0.5, degree: 2, summary: "Post saccadic oscillations in the eye tracker signal..." },
    { id: "2", title: "Production of Supra-regular Spatial Sequences", authors: "Jiang Dehaene Wang", year: "2018", cluster: 1, cluster_color: "#ec4899", x: 0.5, y: -0.5, degree: 1, summary: "Production of supraregular repeat and mirror spatial sequences..." },
    { id: "3", title: "Oxytocin enables maternal behaviour", authors: "Marlin et al.", year: "2015", cluster: 0, cluster_color: "#6366f1", x: -0.5, y: 0.5, degree: 1, summary: "Oxytocin enables maternal behaviour by balancing..." }
  ],
  edges: [
    { source: "1", target: "3", weight: 0.85 }
  ],
  clusters: [
    { id: 0, label: "Cluster 0", color: "#6366f1", count: 2 },
    { id: 1, label: "Cluster 1", color: "#ec4899", count: 1 }
  ],
  stats: {
    n_nodes: 3,
    n_edges: 1,
    n_clusters: 2,
    n_with_authors: 3,
    n_with_year: 3,
    n_with_doi: 2,
    n_with_summary: 3,
    built_at: Date.now()
  }
};

// Override apiFetch to return demo data
window.apiFetch = async (path) => {
  if (path.includes('semantic')) return demoData;
  if (path.includes('citations')) return { edges: [] };
  return { error: 'Not found in demo mode' };
};

console.log("Demo mode active — Mocking graph API");
