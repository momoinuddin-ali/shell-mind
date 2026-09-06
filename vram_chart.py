import json
import matplotlib.pyplot as plt

# 1. Load the recorded VRAM data
try:
    with open('vram_timeline.json', 'r') as f:
        data = json.load(f)
except FileNotFoundError:
    print("Error: vram_timeline.json not found. Run an agent prompt first!")
    exit(1)

# 2. Extract the data points (Zoom in on the final run)
data = data[-22:]  # Grab only the last 22 samples (your 65-second run)
start_time = data[0]['t']
times = [d['t'] - start_time for d in data]  # Normalize time to start at 0s
free_vram = [d['free_gb'] for d in data]
events = [d['event'] for d in data]

# 3. Setup the professional Dark Mode chart
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(12, 6))

# Plot the Free VRAM line
ax.plot(times, free_vram, marker='o', color='#3FB950', linewidth=2.5, markersize=6, label='Free VRAM (GB)')

# Draw hardware boundaries for the RTX 5050
ax.axhline(y=0, color='#B84A4A', linestyle='--', linewidth=2, label='OOM Crash Line (0 GB)')
ax.axhline(y=7.56, color='#8B93A1', linestyle=':', linewidth=1.5, label='Max GPU VRAM (7.56 GB)')

# 4. Annotate the exact moments models swapped in and out
for i, event in enumerate(events):
    if event and event != 'init':
        # Clean up event names for the chart
        label = event.replace('_', ' ').title()
        ax.annotate(label, 
                    (times[i], free_vram[i]), 
                    textcoords="offset points", 
                    xytext=(0, 15), 
                    ha='center', 
                    fontsize=9, 
                    color='#C99B3D',
                    rotation=45)

# 5. Formatting the labels
ax.set_title('Shell-Mind: Zero-Sum VRAM Orchestration (RTX 5050)', fontsize=16, color='#E8E6DE', pad=20)
ax.set_xlabel('Execution Time (seconds)', fontsize=12, color='#8B93A1')
ax.set_ylabel('Available Free VRAM (GB)', fontsize=12, color='#8B93A1')
ax.set_ylim(-0.5, 8.5)
ax.grid(True, color='#2B3340', linestyle='-', alpha=0.5)
ax.legend(loc='lower left', frameon=True, facecolor='#161B22', edgecolor='#2B3340')

# 6. Save the image
plt.tight_layout()
plt.savefig('portfolio_vram_chart.png', dpi=300)
print("✅ Success! Chart saved as 'portfolio_vram_chart.png'")