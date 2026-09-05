/* An inert QProcess for the Qt-for-WebAssembly build.
 *
 * Qt for WebAssembly ships no QProcess: the browser has no fork/exec, so Qt gates the
 * class out (QT_CONFIG(process) is false). FreeCAD's external-tool paths -- Qt Assistant
 * (help), wget (NetworkRetriever), dot/unflatten (GraphvizView), the external-program
 * dialog, and gmsh remeshing -- still reference it from code that must compile. This
 * supplies a QProcess that satisfies every use and does nothing.
 *
 * Force-included (-include) into FreeCADGui, MeshGui, MeshPartGui and Start by their
 * CMakeLists, via patches/freecad.patch.
 *
 * Qt 6.11 changed what <QtCore/qprocess.h> does when the feature is off. 6.9 simply
 * declared nothing; 6.11 declares a PLACEHOLDER `class QProcess` there -- one static
 * splitCommand() and a deleted constructor -- and the same header is where
 * QProcessEnvironment lives, which Gui/Dialogs/DlgAbout.cpp uses. So the placeholder and
 * this stub collided:
 *     qprocess.h:289:7: error: redefinition of 'QProcess'
 * on 16 translation units. The way out that keeps QProcessEnvironment: this header is
 * force-included before anything else, so it takes Qt's header first under a different
 * class name, then defines the real QProcess itself. The rename is one macro around one
 * include; QProcessEnvironment is a different token and is untouched. If a Qt ever ships
 * a real QProcess for wasm (QT_CONFIG(process) true), the stub steps aside entirely.
 *
 * NO Q_OBJECT, DELIBERATELY. A header force-included into hundreds of translation units
 * cannot be run through moc, so this class has no signals. Every connect() to a QProcess
 * *signal* is therefore #if'd out in patches/freecad.patch -- see
 * Mod/Mesh/Gui/RemeshGmsh.cpp, Gui/NetworkRetriever.cpp, Gui/Assistant.cpp and
 * Gui/Dialogs/DlgRunExternal.cpp. It does derive from QObject, because QProcess member
 * functions are used as *slots* -- connect(qApp, &QApplication::lastWindowClosed, wget,
 * &QProcess::kill) and QTimer::singleShot(2000, wget, &QProcess::kill) -- and a
 * member-function slot needs no moc metadata, only a QObject receiver.
 *
 * Behaviour: never starts, always NotRunning, reads return empty, writes are counted and
 * discarded, waits return false immediately (never blocking the browser main thread).
 * Callers already handle "the tool is not installed", which is the truth here.
 *
 * NOTE: this file is a RECONSTRUCTION. The build machine's original was never committed;
 * toolchain/stage-headers.sh prefers an existing copy and only diffs this one against it.
 * See BUILD-WEH.md.
 */
#ifndef FCWEB_QPROCESS_STUB_H
#define FCWEB_QPROCESS_STUB_H

#if defined(__EMSCRIPTEN__)

#include <QtCore/qglobal.h>

#if QT_CONFIG(process)

/* A real QProcess exists in this Qt. Nothing to stub. */
#include <QtCore/qprocess.h>

#else /* !QT_CONFIG(process) */

/* Take Qt's header now, with its placeholder QProcess renamed out of the way, so that
 * QProcessEnvironment is declared and FreeCAD's own #include <QProcess> later finds the
 * include guard already set. See the note at the top. */
#define QProcess FcwebQtPlaceholderQProcess
#include <QtCore/qprocess.h>
#undef QProcess

#include <unistd.h>

#include <QByteArray>
#include <QObject>
#include <QString>
#include <QStringList>

class QProcess: public QObject
{
public:
    enum ProcessState
    {
        NotRunning = 0,
        Starting = 1,
        Running = 2
    };
    enum ExitStatus
    {
        NormalExit = 0,
        CrashExit = 1
    };
    enum ProcessError
    {
        FailedToStart = 0,
        Crashed = 1,
        Timedout = 2,
        ReadError = 3,
        WriteError = 4,
        UnknownError = 5
    };
    enum ProcessChannel
    {
        StandardOutput = 0,
        StandardError = 1
    };
    enum ProcessChannelMode
    {
        SeparateChannels = 0,
        MergedChannels = 1,
        ForwardedChannels = 2
    };

    explicit QProcess(QObject* parent = nullptr)
        : QObject(parent)
    {}
    ~QProcess() override = default;

    // Starting. There is nothing to start; the state never leaves NotRunning, so the
    // state() == QProcess::Running guards every caller writes take the false branch.
    void start(const QString& program, const QStringList& arguments = QStringList())
    {
        m_program = program;
        m_arguments = arguments;
    }
    void start()
    {}
    void setProgram(const QString& program)
    {
        m_program = program;
    }
    void setArguments(const QStringList& arguments)
    {
        m_arguments = arguments;
    }
    QString program() const
    {
        return m_program;
    }
    QStringList arguments() const
    {
        return m_arguments;
    }

    ProcessState state() const
    {
        return NotRunning;
    }
    int exitCode() const
    {
        return -1;
    }
    ExitStatus exitStatus() const
    {
        return CrashExit;
    }
    ProcessError error() const
    {
        return FailedToStart;
    }
    QString errorString() const
    {
        return QStringLiteral("QProcess is not available in the WebAssembly build");
    }

    // Stopping. These are used as connect() targets, which needs no moc.
    void kill()
    {}
    void terminate()
    {}
    void close()
    {}
    void closeWriteChannel()
    {}
    void closeReadChannel(ProcessChannel)
    {}

    // Waiting returns false at once. Returning true would tell the caller a process it
    // never started has finished; blocking would freeze the browser's main thread.
    bool waitForStarted(int /*msecs*/ = 30000)
    {
        return false;
    }
    bool waitForFinished(int /*msecs*/ = 30000)
    {
        return false;
    }
    bool waitForReadyRead(int /*msecs*/ = 30000)
    {
        return false;
    }
    bool waitForBytesWritten(int /*msecs*/ = 30000)
    {
        return false;
    }

    // Reading. Empty, and callers check before use.
    QByteArray readAll()
    {
        return QByteArray();
    }
    QByteArray readAllStandardOutput()
    {
        return QByteArray();
    }
    QByteArray readAllStandardError()
    {
        return QByteArray();
    }
    QByteArray readLine(qint64 /*maxlen*/ = 0)
    {
        return QByteArray();
    }
    bool canReadLine() const
    {
        return false;
    }
    bool atEnd() const
    {
        return true;
    }
    qint64 bytesAvailable() const
    {
        return 0;
    }

    // Writing is accepted and discarded: GraphvizView streams a whole graph in before it
    // checks anything, and reporting a short write there would be a different kind of
    // lie. The byte count is honest about what was consumed.
    qint64 write(const QByteArray& data)
    {
        return static_cast<qint64>(data.size());
    }
    qint64 write(const char* /*data*/, qint64 len)
    {
        return len;
    }
    qint64 write(const char* data)
    {
        return data ? static_cast<qint64>(qstrlen(data)) : 0;
    }

    // Configuration: recorded, never acted on.
    void setReadChannel(ProcessChannel channel)
    {
        m_readChannel = channel;
    }
    ProcessChannel readChannel() const
    {
        return m_readChannel;
    }
    void setProcessChannelMode(ProcessChannelMode mode)
    {
        m_channelMode = mode;
    }
    ProcessChannelMode processChannelMode() const
    {
        return m_channelMode;
    }
    void setWorkingDirectory(const QString& dir)
    {
        m_workingDirectory = dir;
    }
    QString workingDirectory() const
    {
        return m_workingDirectory;
    }
    void setEnvironment(const QStringList& environment)
    {
        m_environment = environment;
    }
    QStringList environment() const
    {
        return m_environment;
    }
    void setStandardOutputFile(const QString&)
    {}
    void setStandardErrorFile(const QString&)
    {}
    void setStandardInputFile(const QString&)
    {}

    // Statics. systemEnvironment() is real -- getenv/environ work under emscripten --
    // because callers pass it straight back into setEnvironment(), and an empty list
    // there would be indistinguishable from "this process has no environment".
    static QStringList systemEnvironment()
    {
        QStringList out;
        for (char** e = ::environ; e && *e; ++e) {
            out.append(QString::fromLocal8Bit(*e));
        }
        return out;
    }
    static bool startDetached(const QString& /*program*/,
                              const QStringList& /*arguments*/ = QStringList(),
                              const QString& /*workingDirectory*/ = QString(),
                              qint64* pid = nullptr)
    {
        if (pid) {
            *pid = 0;
        }
        return false;
    }
    static int execute(const QString& /*program*/,
                       const QStringList& /*arguments*/ = QStringList())
    {
        return -2;  // QProcess's own "failed to start" return value
    }

private:
    QString m_program;
    QStringList m_arguments;
    QString m_workingDirectory;
    QStringList m_environment;
    ProcessChannel m_readChannel = StandardOutput;
    ProcessChannelMode m_channelMode = SeparateChannels;
};

#endif /* QT_CONFIG(process) */

#endif /* __EMSCRIPTEN__ */

#endif /* FCWEB_QPROCESS_STUB_H */
