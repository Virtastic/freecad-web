// Spike (a): trivial Qt6 QtWidgets app for wasm. Highest strategic risk —
// proves the whole desktop-UI pillar can render + dispatch events in the browser.
#include <QApplication>
#include <QWidget>
#include <QVBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <cstdio>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);

    QWidget window;
    window.setWindowTitle("FreeCAD-Web Qt spike");
    auto *layout = new QVBoxLayout(&window);

    auto *label = new QLabel("Qt6 QtWidgets running in WebAssembly");
    auto *button = new QPushButton("Click me");
    layout->addWidget(label);
    layout->addWidget(button);

    int clicks = 0;
    QObject::connect(button, &QPushButton::clicked, [&]() {
        ++clicks;
        label->setText(QString("Button slot fired: %1 click(s)").arg(clicks));
        std::printf("[spike-a] button clicked: %d\n", clicks);
        std::fflush(stdout);
    });

    window.resize(420, 200);
    window.show();
    std::printf("[spike-a] window shown — QApplication::exec()\n");
    std::fflush(stdout);
    return app.exec();
}
