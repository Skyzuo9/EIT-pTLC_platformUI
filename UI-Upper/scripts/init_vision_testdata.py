"""初始化测试数据：将已有的 analysis_output 复制到 data/samples 结构中。"""
from pathlib import Path
from core.sample_store import SampleStore
import shutil

store = SampleStore(root_dir=Path("data/samples"))
print(f"SampleStore root: {store.root_dir}")

# 创建 case1 样品目录
sample_dir = store.create_sample_dir("case1")
print(f"Created: {sample_dir}")

# 复制已有的 analysis_output 作为测试数据
src_analysis = Path("../View/pTLC_Viewing/analysis_output/case1")
dst_analysis = store.get_analysis_dir("case1")

if src_analysis.exists() and not (dst_analysis / "summary.json").exists():
    shutil.copy2(src_analysis / "summary.json", dst_analysis / "summary.json")
    for ext in [".png"]:
        src_img = src_analysis / f"case1{ext}"
        if src_img.exists():
            shutil.copy2(src_img, dst_analysis / f"case1{ext}")
    for subdir in ["task1_task2_contours_paths", "task3_metrics"]:
        src_sub = src_analysis / subdir
        dst_sub = dst_analysis / subdir
        if src_sub.exists() and not dst_sub.exists():
            shutil.copytree(src_sub, dst_sub)
    print(f"Copied analysis data to {dst_analysis}")

# 复制 before/after 图像
src_sample = Path("../View/pTLC_Viewing/sample/case1")
if src_sample.exists():
    for f in src_sample.iterdir():
        if f.is_file():
            shutil.copy2(f, sample_dir / f.name)
    print(f"Copied sample images to {sample_dir}")

# 验证
print(f"has_analysis(case1): {store.has_analysis('case1')}")
print(f"summary_path: {store.get_summary_path('case1')}")
print(f"annotated_image: {store.get_annotated_image_path('case1')}")
print(f"before_path: {store.get_before_path('case1')}")
print(f"after_path: {store.get_after_path('case1')}")
print(f"Samples: {store.list_samples()}")
