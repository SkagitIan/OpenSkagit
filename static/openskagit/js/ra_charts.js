/*--------------------------------------------------------------------
RA CHART SYSTEM (OpenSkagit)
Requires Chart.js v4+
--------------------------------------------------------------------*/

let chart = null;

function updateChartDescription(details, nodes) {
    if (!nodes) return;
    const { title, body, support, ideal } = details || {};
    if (nodes.title) nodes.title.textContent = title || "";
    if (nodes.body) nodes.body.textContent = body || "";
    if (nodes.support) nodes.support.textContent = support || "";
    if (nodes.ideal) nodes.ideal.textContent = ideal || "";
}

function getDescriptionFromButton(button) {
    if (!button) {
        return {};
    }
    return {
        title: button.getAttribute("data-title") || button.textContent.trim() || "",
        body: button.getAttribute("data-body") || "",
        support: button.getAttribute("data-support") || "",
        ideal: button.getAttribute("data-ideal") || "",
    };
}

function drawChart(type, data) {
    const canvas = document.getElementById("raChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const safeData = Array.isArray(data) ? data : [];

    if (chart) {
        chart.destroy();
        chart = null;
    }

    switch (type) {

        /* ----------------------------------------------------------
           1. Ratio Histogram
        ---------------------------------------------------------- */
        case "ratio_dist": {
            const ratios = safeData
                .map(d => d.ratio_final ?? d.ratio_adj ?? d.ratio)
                .filter(r => typeof r === "number" && !Number.isNaN(r));
            const ratioLabels = ratios.map(r => Number(r).toFixed(3));

            chart = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: ratioLabels,
                    datasets: [{
                        label: "Ratio",
                        data: ratios,
                        backgroundColor: "#7FA693",
                        borderWidth: 0,
                    }]
                },
                options: {
                    plugins: {legend: {display: false}},
                    scales: {
                        x: {
                            title: {display: true, text: "Ratio"},
                            ticks: {autoSkip: true, maxTicksLimit: 20}
                        },
                        y: {
                            title: {display: true, text: "Count"}
                        }
                    }
                }
            });

            break;
        }

        /* ----------------------------------------------------------
           2. Ratio vs Predicted Value
        ---------------------------------------------------------- */
        case "ratio_vs_value": {
            const pts = safeData.map(d => ({
                x: d.Vhat,
                y: d.ratio_final ?? d.ratio_adj ?? d.ratio
            }));

            chart = new Chart(ctx, {
                type: "scatter",
                data: { datasets: [{
                    data: pts,
                    backgroundColor: "#7FA693",
                    pointRadius: 3
                }]},
                options: {
                    plugins: {legend: {display: false}},
                    scales: {
                        x: { title: {display: true, text: "Predicted Value"} },
                        y: { title: {display: true, text: "Ratio"} }
                    }
                }
            });

            break;
        }

        /* ----------------------------------------------------------
           3. Residuals vs Predicted
        ---------------------------------------------------------- */
        case "residuals": {
            const pts = safeData.map(d => ({
                x: d.Vhat,
                y: d.residual
            }));

            chart = new Chart(ctx, {
                type: "scatter",
                data: { datasets: [{
                    data: pts,
                    backgroundColor: "#7FA693",
                    pointRadius: 3
                }]},
                options: {
                    plugins: {legend: {display: false}},
                    scales: {
                        x: { title: {display: true, text: "Predicted Value"} },
                        y: { title: {display: true, text: "Residual"} }
                    }
                }
            });

            break;
        }

        /* ----------------------------------------------------------
           4. Area Bias (log area vs ratio)
        ---------------------------------------------------------- */
        case "area_bias": {
            const pts = safeData.map(d => ({
                x: d.log_area,
                y: d.ratio_final ?? d.ratio_adj ?? d.ratio
            }));

            chart = new Chart(ctx, {
                type: "scatter",
                data: { datasets: [{
                    data: pts,
                    backgroundColor: "#7FA693",
                    pointRadius: 3
                }]},
                options: {
                    plugins: {legend: {display: false}},
                    scales: {
                        x: { title: {display: true, text: "log(area)"} },
                        y: { title: {display: true, text: "Ratio"} }
                    }
                }
            });

            break;
        }

        /* ----------------------------------------------------------
           5. Time Trend (t vs ratio)
        ---------------------------------------------------------- */
        case "time_trend": {
            const pts = safeData.map(d => ({
                x: d.t,
                y: d.ratio_final ?? d.ratio_adj ?? d.ratio
            }));

            chart = new Chart(ctx, {
                type: "scatter",
                data: { datasets: [{
                    data: pts,
                    backgroundColor: "#7FA693",
                    pointRadius: 3
                }]},
                options: {
                    plugins: {legend: {display: false}},
                    scales: {
                        x: { title: {display: true, text: "Time Index (t)"} },
                        y: { title: {display: true, text: "Ratio"} }
                    }
                }
            });

            break;
        }
    }
}

/*--------------------------------------------------------------------
Button Handlers
--------------------------------------------------------------------*/
document.addEventListener("DOMContentLoaded", () => {

    const buttons = Array.from(document.querySelectorAll(".chart-btn"));
    if (!buttons.length) {
        return;
    }
    const defaultButton = document.querySelector('.chart-btn[data-chart="ratio_dist"]') || buttons[0];
    const descriptionNodes = {
        title: document.getElementById("chartDescriptionTitle"),
        body: document.getElementById("chartDescriptionBody"),
        support: document.getElementById("chartDescriptionSupport"),
        ideal: document.getElementById("chartDescriptionIdeal"),
    };
    const descriptions = new Map();
    buttons.forEach(btn => {
        const key = btn.getAttribute("data-chart");
        if (!key) return;
        descriptions.set(key, getDescriptionFromButton(btn));
    });
    const chartData = Array.isArray(window.chartData) ? window.chartData : [];

    const activateChart = (button) => {
        if (!button) {
            return;
        }

        // Handle active state
        buttons.forEach(b => {
            b.classList.remove("bg-[#7FA693]", "text-white");
            b.classList.add("bg-gray-200", "text-gray-700");
        });

        button.classList.remove("bg-gray-200", "text-gray-700");
        button.classList.add("bg-[#7FA693]", "text-white");

        const chartKey = button.getAttribute("data-chart");
        const description = descriptions.get(chartKey) || getDescriptionFromButton(button);
        updateChartDescription(description, descriptionNodes);

        if (!chartKey) {
            return;
        }

        try {
            drawChart(chartKey, chartData);
        } catch (error) {
            console.error("Failed to render regression diagnostics chart.", error);
        }
    };

    buttons.forEach(btn => {
        btn.addEventListener("click", () => activateChart(btn));
    });

    activateChart(defaultButton);
});
