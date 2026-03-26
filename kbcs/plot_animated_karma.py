import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import os

def create_animation():
    csv_file = 'results/karma_log.csv'
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Run traffic test first.")
        return

    df = pd.read_csv(csv_file)
    if df.empty:
        print("Data is empty.")
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Setup axis limits
    ax.set_ylim(0, 110)
    ax.set_xlim(0, max(1, df['time_sec'].max()))
    
    # Lines
    line_cubic, = ax.plot([], [], lw=2, color='red', label='CUBIC (Aggressive)')
    line_bbr, = ax.plot([], [], lw=2, color='blue', label='BBR (Model-based)')
    
    # Thresholds
    ax.axhline(80, color='green', linestyle='--', alpha=0.5, label='High (Green)')
    ax.axhline(40, color='orange', linestyle='--', alpha=0.5, label='Low (Yellow)')
    ax.axhspan(0, 40, color='red', alpha=0.1, label='RED ZONE (Drops)')
    
    ax.set_xlabel('Time (seconds)')
    ax.set_ylabel('Karma Score')
    ax.set_title('KBCS Real-Time Karma Dynamics (E12)')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    def init():
        line_cubic.set_data([], [])
        line_bbr.set_data([], [])
        return line_cubic, line_bbr

    def animate(i):
        # i represents the number of frames to include
        subset = df.iloc[:i]
        line_cubic.set_data(subset['time_sec'], subset['cubic_karma'])
        line_bbr.set_data(subset['time_sec'], subset['bbr_karma'])
        return line_cubic, line_bbr

    print("Generating animation (this may take a minute)...")
    anim = animation.FuncAnimation(fig, animate, init_func=init,
                                   frames=len(df), interval=50, blit=True)
    
    os.makedirs('results', exist_ok=True)
    # Save as gif using pillow
    anim.save('results/karma_animation.gif', writer='pillow', fps=20)
    print("Saved animation to results/karma_animation.gif")
    
    # Also save a static final plot
    fig2, ax2 = plt.subplots(figsize=(10, 5))
    ax2.plot(df['time_sec'], df['cubic_karma'], lw=2, color='red', label='CUBIC')
    ax2.plot(df['time_sec'], df['bbr_karma'], lw=2, color='blue', label='BBR')
    ax2.axhline(80, color='green', linestyle='--', alpha=0.5)
    ax2.axhline(40, color='orange', linestyle='--', alpha=0.5)
    ax2.axhspan(0, 40, color='red', alpha=0.1)
    ax2.set_ylim(0, 110)
    ax2.set_xlabel('Time (seconds)')
    ax2.set_ylabel('Karma Score')
    ax2.set_title('KBCS Karma Dynamics (Final State)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    fig2.savefig('results/karma_static.png')
    print("Saved static plot to results/karma_static.png")

if __name__ == '__main__':
    create_animation()
