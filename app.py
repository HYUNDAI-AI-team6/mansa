import gradio as gr


def main():
    with gr.Blocks(title="MANSA") as demo:
        gr.Markdown("# MANSA")
        gr.Markdown("안전기술서 프로젝트 개발환경이 정상적으로 실행되었습니다.")

    demo.launch()


if __name__ == "__main__":
    main()