"use strict";
const plan = JSON.parse(document.getElementById("plan-data").textContent);
const map = L.map("map");
const tiles = L.tileLayer(`/map/${plan.plan_id}/tiles/{z}/{x}/{y}.png`, {maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> · <a href="https://www.geoapify.com/">Geoapify</a>'}).addTo(map);
tiles.on("tileerror", () => {document.getElementById("map-status").textContent = "Background tiles unavailable. The verified route and fuel stops remain displayed.";});
const route = L.geoJSON(plan.route.geometry, {style: {color: "#2368bb", weight: 5}}).addTo(map);
if (plan.route.geometry.type === "Point") {map.setView([plan.input.start.latitude, plan.input.start.longitude], 13);} else {map.fitBounds(route.getBounds(), {padding: [25,25]});}
for (const [label, point] of [["Start",plan.input.start],["Finish",plan.input.finish]]) {L.marker([point.latitude,point.longitude]).addTo(map).bindPopup(label);}
for (const station of plan.visited_stations) {
  const stop = plan.fuel_stops.find(s => s.visited_station_sequence === station.sequence);
  const text = document.createElement("div");
  text.textContent = `${station.sequence}. ${station.name}: ${stop ? `${Number(stop.gallons_purchased).toFixed(3)} gal, $${stop.cost_usd}` : "visited without purchase"}`;
  L.circleMarker([station.routed_location.latitude,station.routed_location.longitude], {radius: 9,color: stop ? "#147750" : "#68717b"}).addTo(map).bindPopup(text);
}
